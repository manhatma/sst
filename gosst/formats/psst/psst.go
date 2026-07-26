package psst

import (
	"bufio"
	"errors"
	"fmt"
	"math"
	"reflect"
	"strings"

	"github.com/SeanJxie/polygo"
	"github.com/google/uuid"
	"github.com/openacid/slimarray/polyfit"
	"github.com/ugorji/go/codec"
	"gonum.org/v1/gonum/floats"
	"golang.org/x/exp/constraints"
)

const (
	FORK_TRAVEL_PER_LSB                  = 0.00758	// (mm/LSB) fork quantisation
	SHOCK_TRAVEL_PER_LSB                 = 0.00284	// (mm/LSB) shock quantisation
	IDLING_DURATION_THRESHOLD           = 0.10	// (s) minimum duration to consider stroke an idle period
	AIRTIME_TRAVEL_THRESHOLD            = 3		// (mm) maximum travel above top-out to consider stroke an airtime candidate
	AIRTIME_DURATION_THRESHOLD          = 0.20	// (s) minimum duration to consider stroke an airtime candidate
	AIRTIME_VELOCITY_THRESHOLD          = 500	// (mm/s) minimum velocity after stroke to consider it an airtime candidate
	AIRTIME_OVERLAP_THRESHOLD           = 0.5	// f&r airtime candidates must overlap at least this fraction of the SHORTER one
	AIRTIME_SETTLED_TRAVEL_RATIO        = 0.08	// each end must rest within maxTravel*this of ITS OWN top-out to confirm an airtime
	STROKE_LENGTH_THRESHOLD             = 0.5 	// (mm) minimum length to consider stroke a compression/rebound
    STROKE_LENGTH_THRESHOLD_FAC         = 30 	// factor for airtime detection with respect to small stroke length threshold
	TRAVEL_HIST_BINS                    = 20	// number of travel histogram bins
	VELOCITY_HIST_TRAVEL_BINS           = 20	// number of travel histogram bins for velocity histogram
	VELOCITY_HIST_STEP                  = 100.0	// (mm/s) step between velocity histogram bins
	VELOCITY_HIST_STEP_FINE             = 10 	// (mm/s) step between fine-grained velocity histogram bins
	BOTTOMOUT_THRESHOLD                 = 2.5	// (mm) bottomouts are regions where travel > max_travel - this value

	// Single-sample velocity spike rejection (matches Sufni.Bridge
	// Parameters.SpikeJerkLimit). After the central difference, an isolated
	// outlier whose deviation from the linear interpolation of its neighbours
	// implies a per-sample jerk above this bound is replaced by that
	// interpolation. Catches isolated 1-sample ADC glitches without clipping
	// real impact peaks.
	SPIKE_JERK_LIMIT = 5.0e9	// (mm/s³)

	// Airtime top-out and settling model (matches Sufni.Bridge Parameters).
	// travel == 0 is not a reliable top-out reference: calibration offsets,
	// coil preload, top-out bumpers and the shock->wheel polynomial shift the
	// fully-extended reading by several mm (measured 0.3-6.3 mm across real
	// bikes), so a fixed absolute travel gate can make a perfectly good shock
	// structurally ineligible for the f&r overlap test. Instead each side's
	// top-out is estimated per-session as a low travel quantile (capped as a
	// fraction of max travel, in case the quantile lands on a genuine stroke
	// rather than a flat rest) and every downstream airtime check is relative
	// to that estimate.
	TOP_OUT_QUANTILE  = 0.005	// travel quantile used as the top-out estimate
	TOP_OUT_MAX_RATIO = 0.06	// cap the top-out estimate at maxTravel*this

	// AIRTIME_TRAVEL_THRESHOLD_RATIO scales the top-out-relative airtime
	// travel gate with suspension size, alongside the fixed
	// AIRTIME_TRAVEL_THRESHOLD (the larger of the two applies).
	AIRTIME_TRAVEL_THRESHOLD_RATIO = 0.025

	// AIRTIME_CREEP_RATE and AIRTIME_DURATION_MAX bound the air-candidate
	// test on stroke length. Stiction means a topped-out shock is not
	// perfectly still: it creeps out under its own spring force at up to
	// roughly 13 mm/s, so a hover held for the AIRTIME_DURATION_THRESHOLD
	// window can accumulate several mm of length that a fixed
	// STROKE_LENGTH_THRESHOLD alone would reject. The allowed length budget
	// therefore grows with the stroke's own duration. AIRTIME_DURATION_MAX
	// caps the other end: a bike leaning, hanging or being carried also
	// reads as long, dead-still hover followed by a hard-set-down, and only
	// duration tells the two apart (1.2 s of true hang time already implies
	// a ~1.8 m vertical launch, well beyond anything seen in ridden data).
	AIRTIME_CREEP_RATE   = 15.0	// (mm/s) stroke-length budget added per second of hover
	AIRTIME_DURATION_MAX = 1.2	// (s) maximum duration still considered a single airtime candidate

	// AIRTIME_SETTLE_FRACTION and AIRTIME_QUIESCENT_VELOCITY define what it
	// means for a side to actually be "at rest" during a candidate airtime.
	// Travel alone cannot separate a jump from a manual: an averaged or
	// tail-sample check can be fooled by a topped-out fork masking a loaded
	// shock (the classic manual false positive), and both ends of the bike
	// are typically still moving right at a stroke's edges (the far end
	// still unloading as the near end tops out, or touching back down while
	// the near end is still airborne). What is unambiguous is a contiguous
	// interior run where travel sits near top-out AND velocity is small: an
	// airborne element merely creeps (a few mm/s to a few tens of mm/s)
	// while a grounded one is driven by the terrain (hundreds to
	// low-thousands of mm/s). AIRTIME_QUIESCENT_VELOCITY is the boundary
	// between those two regimes; AIRTIME_SETTLE_FRACTION is the minimum
	// share of the stroke that run must cover.
	AIRTIME_SETTLE_FRACTION    = 0.25	// minimum contiguous fraction of the stroke that must be at rest
	AIRTIME_QUIESCENT_VELOCITY = 150	// (mm/s) maximum |velocity| while resting at top-out

	// CurrentProcessingVersion gates ReprocessVelocityFromBlob: a stored blob whose
	// ProcessingVersion is already >= this is left untouched, so bumping it is
	// required whenever a change here (like the airtime rework above) needs to be
	// applied to existing sessions.
	CurrentProcessingVersion = 6

	// Whittaker-Henderson smoother for travel→velocity differentiation.
	// Setup: ADS1115 PGA 4.096 V, sensor swing 0–3.3 V → 26400 usable codes (log2 = 14.6883).
	// VLP200 fork:    7.58 µm/LSB, sub-LSB threshold 6.5 mm/s.
	// ELPM75 shock:   2.84 µm/LSB on shock travel, 2.4 mm/s sub-LSB threshold (rear pipeline
	//                 smooths shock travel before the leverage polynomial to keep this finer
	//                 quantisation; see SmoothedRearWheelTravel).
	// f_c/f_s ≈ (1/2π)·λ^(−1/2p): order 3, λ 11 → −3 dB at ~91 Hz @ 860 SPS, steeper roll-off
	// than the previous (2, 5) at the same cutoff so the central-difference noise gain
	// above f_s/4 is suppressed without sacrificing impulse fidelity on rock/square-edge hits.
	WH_ORDER  = 3
	WH_LAMBDA = 11
)

// (mm/s) velocity dead bands are the per-side LSB size multiplied by the actual sample rate.
// At 860.58 Hz: fork = 0.00758 mm/LSB * 860.58 Hz = 6.52 mm/s;
// shock = 0.00284 mm/LSB * 860.58 Hz = 2.44 mm/s.
func forkVelocityZeroThreshold(sampleRate uint16) float64 {
	return FORK_TRAVEL_PER_LSB * float64(sampleRate)
}

func shockVelocityZeroThreshold(sampleRate uint16) float64 {
	return SHOCK_TRAVEL_PER_LSB * float64(sampleRate)
}

// smoothedRearWheelTravel smooths the rear shock-travel signal with WH (where ADS1115
// quantisation is ~2.84 µm/LSB for an ELPM75 versus ~7 µm/LSB after the leverage
// polynomial), then maps the smoothed shock signal through the polynomial to obtain
// wheel travel for differentiation. Compared to smoothing already-mapped wheel travel,
// this gives the WH filter ~2.5× finer input resolution.
func smoothedRearWheelTravel(shockTravel []float64, smoother *WhittakerHendersonSmoother, linkage *Linkage) ([]float64, error) {
	smoothedShock, err := smoother.Smooth(shockTravel)
	if err != nil {
		return nil, err
	}
	n := len(smoothedShock)
	smoothedWheel := make([]float64, n)
	maxRear := linkage.MaxRearTravel
	for i := 0; i < n; i++ {
		w := linkage.polynomial.At(smoothedShock[i])
		if w < 0 {
			w = 0
		}
		if w > maxRear {
			w = maxRear
		}
		smoothedWheel[i] = w
	}
	return smoothedWheel, nil
}

// calculateDerivative computes the derivative with a 5-tap central difference for interior
// samples (4th-order accurate), falling back to 3-tap one sample in from each edge and
// forward/backward differences at the boundary. The wider aperture bridges the LSB plateaus
// that occur during slow motion (< ~6 mm/s on the wheel-travel side) where consecutive
// samples sit on the same ADC code and the 3-tap derivative would emit zeros.
func calculateDerivative(data []float64, sampleRate uint16) ([]float64, error) {
	n := len(data)
	if n == 0 {
		return []float64{}, nil
	}
	if sampleRate == 0 {
		return nil, errors.New("SampleRate darf für die Ableitungsberechnung nicht Null sein")
	}

	fs := float64(sampleRate)
	derivative := make([]float64, n)

	if n == 1 {
		derivative[0] = 0
		return derivative, nil
	}

	// Forward at start, 3-tap one sample in, 5-tap interior, 3-tap one before end, backward at end.
	// 5-tap central difference: v[i] = (-x[i-2] - 8 x[i-1] + 8 x[i+1] + x[i+2]) / (12 dt).
	derivative[0] = (data[1] - data[0]) * fs
	if n >= 3 {
		derivative[1] = (data[2] - data[0]) * fs / 2.0
	}

	for i := 2; i < n-2; i++ {
		derivative[i] = (-data[i-2] - 8.0*data[i-1] + 8.0*data[i+1] + data[i+2]) * fs / 12.0
	}

	if n >= 3 {
		derivative[n-2] = (data[n-1] - data[n-3]) * fs / 2.0
	}
	derivative[n-1] = (data[n-1] - data[n-2]) * fs

	rejectSingleSampleSpikes(derivative, sampleRate)
	return derivative, nil
}

// rejectSingleSampleSpikes replaces isolated 1-sample velocity outliers with the
// linear interpolation of their neighbours. Ported from Sufni.Bridge's
// RejectSingleSampleSpikes: the Taylor expansion v[i]−½(v[i-1]+v[i+1]) ≈
// −½·dt²·jerk, so a deviation above ½·dt²·SPIKE_JERK_LIMIT implies a non-physical
// per-sample jerk. The local velocity gradient drops out, so legitimate fast
// transitions pass untouched.
func rejectSingleSampleSpikes(v []float64, sampleRate uint16) {
	if len(v) < 3 {
		return
	}
	dt := 1.0 / float64(sampleRate)
	floor := 0.5 * SPIKE_JERK_LIMIT * dt * dt
	for i := 1; i < len(v)-1; i++ {
		expected := 0.5 * (v[i-1] + v[i+1])
		if math.Abs(v[i]-expected) > floor {
			v[i] = expected
		}
	}
}

type LinkageRecord struct {
	ShockTravel   float64
	WheelTravel   float64
	LeverageRatio float64
}

type Linkage struct {
	Id               uuid.UUID    `codec:"-" db:"id"           json:"id"`
	Name             string       `codec:"," db:"name"         json:"name"         binding:"required"`
	HeadAngle        float64      `codec:"," db:"head_angle"   json:"head_angle"   binding:"required"`
	RawData          string       `codec:"-" db:"raw_lr_data"  json:"data"         binding:"required"`
	MaxFrontStroke   float64      `codec:"," db:"front_stroke" json:"front_stroke" binding:"required"`
	MaxRearStroke    float64      `codec:"," db:"rear_stroke"  json:"rear_stroke"  binding:"required"`
	MaxFrontTravel   float64      `codec:","                   json:"-"`
	MaxRearTravel    float64      `codec:","                   json:"-"`
	LeverageRatio    [][2]float64 `codec:","                   json:"-"`
	ShockWheelCoeffs []float64    `codec:","                   json:"-"`
	polynomial       *polygo.RealPolynomial
}

type suspension struct {
	Present                bool
	Calibration            Calibration
	Travel                 []float64
	Velocity               []float64
	Strokes                strokes
	TravelBins             []float64
	VelocityBins           []float64
	FineVelocityBins       []float64
	GlobalMaxTravelAllData float64
	GlobalP95TravelAllData float64
	GlobalAvgTravelAllData float64
	// Raw shock/damper travel before the leverage polynomial. Only populated for the rear
	// suspension; nil for front (where the head-angle factor is linear). Used to smooth on
	// the finer-quantised shock signal (~2.84 µm/LSB) instead of the polynomial-mapped wheel
	// travel (~7 µm/LSB). Older blobs deserialise it as nil; reprocessSuspension reconstructs
	// it via wheelToDamperTravel.
	ShockTravel []float64
}

type Number interface {
	constraints.Float | constraints.Integer
}

type Meta struct {
	Name       string
	Version    uint8
	SampleRate uint16
	Timestamp  int64
}

type SetupData struct {
	Linkage          *Linkage
	FrontCalibration *Calibration
	RearCalibration  *Calibration
}

type Processed struct {
	Meta
	ProcessingVersion int
	Front    suspension
	Rear     suspension
	Linkage  Linkage
	Airtimes []*airtime
}

func (this *Linkage) ProcessRawData() error {
	var records []LinkageRecord
	scanner := bufio.NewScanner(strings.NewReader(this.RawData))
	prev_w := 0.0
	s := 0.0
	for scanner.Scan() {
		var w, l float64
		_, err := fmt.Sscanf(scanner.Text(), "%f,%f", &w, &l)
		if err == nil {
			records = append(records, LinkageRecord{
				ShockTravel:   s,
				WheelTravel:   w,
				LeverageRatio: l,
			})
			s += (w - prev_w) / l
			prev_w = w
		}
	}
	this.Process(records)
	return nil
}

func (this *Linkage) Process(records []LinkageRecord) {
	var st []float64
	var wt []float64
	var wtlr [][2]float64

	for _, record := range records {
		st = append(st, record.ShockTravel)
		wt = append(wt, record.WheelTravel)
		wtlr = append(wtlr, [2]float64{record.WheelTravel, record.LeverageRatio})
	}

	f := polyfit.NewFit(st, wt, 3)
	this.LeverageRatio = wtlr
	this.ShockWheelCoeffs = f.Solve()
	// Force the shock→wheel polynomial through (0,0): unconstrained least-squares
	// leaves a non-zero constant term that biases every rear-travel sample, so the
	// signal never returns to 0 even when the shock is fully extended (airtime).
	this.ShockWheelCoeffs[0] = 0
	this.polynomial, _ = polygo.NewRealPolynomial(this.ShockWheelCoeffs)
	this.MaxRearTravel = this.polynomial.At(this.MaxRearStroke)
	this.MaxFrontTravel = math.Sin(this.HeadAngle*math.Pi/180.0) * this.MaxFrontStroke
}

// WheelToDamperTravel converts a wheel-travel sample (mm) back to damper/shock travel (mm)
// by numerically inverting the shock→wheel polynomial via binary search. The polynomial is
// monotonically increasing on [0, MaxRearStroke] for a real linkage, so 50 iterations
// converge to machine precision.
func (this *Linkage) WheelToDamperTravel(wheelTravel float64) float64 {
	maxShock := this.MaxRearStroke
	if maxShock <= 0 || this.polynomial == nil {
		return 0
	}
	lo := 0.0
	hi := maxShock
	for i := 0; i < 50; i++ {
		mid := (lo + hi) / 2.0
		if this.polynomial.At(mid) < wheelTravel {
			lo = mid
		} else {
			hi = mid
		}
	}
	mid := (lo + hi) / 2.0
	if mid < 0 {
		return 0
	}
	if mid > maxShock {
		return maxShock
	}
	return mid
}

func linspace(min, max float64, num int) []float64 {
	if num <= 0 {
		return []float64{}
	}
	if num == 1 {
		return []float64{min}
	}
	step := (max - min) / float64(num-1)
	bins := make([]float64, num)
	for i := range bins {
		bins[i] = min + step*float64(i)
	}
	return bins
}

type MissingRecordsError struct{}

func (e *MissingRecordsError) Error() string { return "Front- und Rear-Record-Arrays sind leer" }

// RecordCountMismatchError is not explicitly used in the current logic when WH is enabled,
// since Front and Rear can be smoothed independently.
// type RecordCountMismatchError struct{}
// func (e *RecordCountMismatchError) Error() string { return "Number of Front and Rear records does not match" }

func ProcessRecording[T Number](front, rear []T, meta Meta, setup *SetupData) (*Processed, error) {
	var pd Processed
	pd.Meta = meta
	pd.Front.Calibration = *setup.FrontCalibration
	pd.Rear.Calibration = *setup.RearCalibration
	pd.Linkage = *setup.Linkage

	fc := len(front)
	rc := len(rear)
	pd.Front.Present = fc != 0
	pd.Rear.Present = rc != 0

	if !(pd.Front.Present || pd.Rear.Present) {
		return nil, &MissingRecordsError{}
	}

	if pd.Front.Present {
		pd.Front.Travel = make([]float64, fc)
		front_coeff := math.Sin(pd.Linkage.HeadAngle * math.Pi / 180.0)
		for idx, value := range front {
			out, _ := pd.Front.Calibration.Evaluate(float64(value))
			x := out * front_coeff
			x = math.Max(0, x)
			x = math.Min(x, pd.Linkage.MaxFrontTravel)
			pd.Front.Travel[idx] = x
		}

		if len(pd.Front.Travel) > 0 {
			pd.Front.GlobalMaxTravelAllData = floats.Max(pd.Front.Travel)
			pd.Front.GlobalP95TravelAllData = getPercentileValue(pd.Front.Travel, 0.95)
			pd.Front.GlobalAvgTravelAllData = floats.Sum(pd.Front.Travel) / float64(len(pd.Front.Travel))
		}

		var dtFront []int
		if pd.Linkage.MaxFrontTravel > 0 {
			tbins := linspace(0, pd.Linkage.MaxFrontTravel, TRAVEL_HIST_BINS+1)
			dtFront = digitize(pd.Front.Travel, tbins)
			pd.Front.TravelBins = tbins
		} else {
			pd.Front.TravelBins = []float64{}
			dtFront = make([]int, fc)
		}
		// pd.Front.Strokes.digitizeTravel(dtFront) // legacy call

		minPointsForWH := WH_ORDER + 1
		if fc >= minPointsForWH && pd.Meta.SampleRate > 0 {
			whsFront, errWhs := NewWhittakerHendersonSmoother(fc, WH_ORDER, WH_LAMBDA)
			if errWhs == nil {
				smoothedTravel, errSmooth := whsFront.Smooth(pd.Front.Travel)
				if errSmooth == nil {
					velocity, errVel := calculateDerivative(smoothedTravel, pd.Meta.SampleRate)
					if errVel == nil {
						pd.Front.Velocity = velocity
					} else {
						fmt.Printf("Warning: Error calculating front velocity: %v. Using zero velocity instead.\n", errVel)
						pd.Front.Velocity = make([]float64, fc)
					}
				} else {
					fmt.Printf("Warning: Error smoothing front travel data: %v. Using zero velocity instead.\n", errSmooth)
					pd.Front.Velocity = make([]float64, fc)
				}
			} else {
				fmt.Printf("Warning: Failed to create WH smoother for front travel: %v. Using zero velocity instead.\n", errWhs)
				pd.Front.Velocity = make([]float64, fc)
			}
		} else {
			if fc < minPointsForWH {
				fmt.Printf("Warning: Not enough front data points (%d) for WH smoother (minimum %d required for order %d). Using zero velocity instead.\n", fc, minPointsForWH, WH_ORDER)
			}
			if pd.Meta.SampleRate == 0 {
				fmt.Printf("Warning: Front sample rate is zero; velocity cannot be computed. Using zero velocity instead.\n")
			}
			pd.Front.Velocity = make([]float64, fc)
		}

		vbins, dv := digitizeVelocity(pd.Front.Velocity, VELOCITY_HIST_STEP)
		pd.Front.VelocityBins = vbins
		vbinsFine, dvFine := digitizeVelocity(pd.Front.Velocity, VELOCITY_HIST_STEP_FINE)
		pd.Front.FineVelocityBins = vbinsFine

		currentStrokes := filterStrokes(pd.Front.Velocity, pd.Front.Travel, pd.Linkage.MaxFrontTravel, pd.Meta.SampleRate,
			forkVelocityZeroThreshold(pd.Meta.SampleRate))
		pd.Front.Strokes.categorize(currentStrokes, pd.Front.Travel, pd.Linkage.MaxFrontTravel)

		if len(pd.Front.Strokes.Compressions) == 0 && len(pd.Front.Strokes.Rebounds) == 0 {
			pd.Front.Present = false
		} else {
			// pd.Front.Strokes.digitizeVelocity(dv, dvFine) // legacy call
			pd.Front.Strokes.digitize(dtFront, dv, dvFine)
		}
	}

	if pd.Rear.Present {
		pd.Rear.Travel = make([]float64, rc)
		pd.Rear.ShockTravel = make([]float64, rc)
		for idx, value := range rear {
			shock, _ := pd.Rear.Calibration.Evaluate(float64(value))
			pd.Rear.ShockTravel[idx] = shock
			x := pd.Linkage.polynomial.At(shock)
			x = math.Max(0, x)
			x = math.Min(x, pd.Linkage.MaxRearTravel)
			pd.Rear.Travel[idx] = x
		}

		if len(pd.Rear.Travel) > 0 {
			pd.Rear.GlobalMaxTravelAllData = floats.Max(pd.Rear.Travel)
			pd.Rear.GlobalP95TravelAllData = getPercentileValue(pd.Rear.Travel, 0.95)
			pd.Rear.GlobalAvgTravelAllData = floats.Sum(pd.Rear.Travel) / float64(len(pd.Rear.Travel))
		}

		var dtRear []int
		if pd.Linkage.MaxRearTravel > 0 {
			tbins := linspace(0, pd.Linkage.MaxRearTravel, TRAVEL_HIST_BINS+1)
			dtRear = digitize(pd.Rear.Travel, tbins)
			pd.Rear.TravelBins = tbins
		} else {
			pd.Rear.TravelBins = []float64{}
			dtRear = make([]int, rc)
		}
		// pd.Rear.Strokes.digitizeTravel(dtRear) // legacy call

		minPointsForWH := WH_ORDER + 1
		if rc >= minPointsForWH && pd.Meta.SampleRate > 0 {
			whsRear, errWhs := NewWhittakerHendersonSmoother(rc, WH_ORDER, WH_LAMBDA)
			if errWhs == nil {
				smoothedWheel, errSmooth := smoothedRearWheelTravel(pd.Rear.ShockTravel, whsRear, &pd.Linkage)
				if errSmooth == nil {
					velocity, errVel := calculateDerivative(smoothedWheel, pd.Meta.SampleRate)
					if errVel == nil {
						pd.Rear.Velocity = velocity
					} else {
						fmt.Printf("Warning: Error calculating rear velocity: %v. Using zero velocity instead.\n", errVel)
						pd.Rear.Velocity = make([]float64, rc)
					}
				} else {
					fmt.Printf("Warning: Error smoothing rear shock-travel data: %v. Using zero velocity instead.\n", errSmooth)
					pd.Rear.Velocity = make([]float64, rc)
				}
			} else {
				fmt.Printf("Warning: Failed to create WH smoother for rear travel: %v. Using zero velocity instead.\n", errWhs)
				pd.Rear.Velocity = make([]float64, rc)
			}
		} else {
			if rc < minPointsForWH {
				fmt.Printf("Warning: Not enough rear data points (%d) for WH smoother (minimum %d required for order %d). Using zero velocity instead.\n", rc, minPointsForWH, WH_ORDER)
			}
			if pd.Meta.SampleRate == 0 {
				fmt.Printf("Warning: Rear sample rate is zero; velocity cannot be computed. Using zero velocity instead.\n")
			}
			pd.Rear.Velocity = make([]float64, rc)
		}

		vbins, dv := digitizeVelocity(pd.Rear.Velocity, VELOCITY_HIST_STEP)
		pd.Rear.VelocityBins = vbins
		vbinsFine, dvFine := digitizeVelocity(pd.Rear.Velocity, VELOCITY_HIST_STEP_FINE)
		pd.Rear.FineVelocityBins = vbinsFine

		currentStrokes := filterStrokes(pd.Rear.Velocity, pd.Rear.Travel, pd.Linkage.MaxRearTravel, pd.Meta.SampleRate,
			shockVelocityZeroThreshold(pd.Meta.SampleRate))
		pd.Rear.Strokes.categorize(currentStrokes, pd.Rear.Travel, pd.Linkage.MaxRearTravel)
		if len(pd.Rear.Strokes.Compressions) == 0 && len(pd.Rear.Strokes.Rebounds) == 0 {
			pd.Rear.Present = false
		} else {
			// pd.Rear.Strokes.digitizeVelocity(dv, dvFine) // legacy call
			pd.Rear.Strokes.digitize(dtRear, dv, dvFine)
		}
	}

	pd.airtimes()
	pd.ProcessingVersion = CurrentProcessingVersion
	return &pd, nil
}

// reprocessSuspension recomputes velocity, bins, strokes and histograms
// from the stored Travel array using current smoothing parameters.
// For rear suspension (linkage != nil), the smoother is applied to the
// finer-quantised shock-travel signal and the result is mapped back through
// the leverage polynomial. ShockTravel is reconstructed from the stored
// Travel via Linkage.WheelToDamperTravel for sessions imported before the
// field existed.
func reprocessSuspension(s *suspension, sampleRate uint16, maxTravel, velocityZeroThreshold float64, linkage *Linkage) {
	n := len(s.Travel)
	if n == 0 || !s.Present {
		return
	}

	// Travel bins
	var dt []int
	if maxTravel > 0 {
		tbins := linspace(0, maxTravel, TRAVEL_HIST_BINS+1)
		dt = digitize(s.Travel, tbins)
		s.TravelBins = tbins
	} else {
		s.TravelBins = []float64{}
		dt = make([]int, n)
	}

	// Smooth + differentiate
	minPointsForWH := WH_ORDER + 1
	if n >= minPointsForWH && sampleRate > 0 {
		whs, err := NewWhittakerHendersonSmoother(n, WH_ORDER, WH_LAMBDA)
		if err == nil {
			var smoothedWheel []float64
			var smoothErr error
			if linkage != nil && linkage.polynomial != nil {
				// Rear: smooth on shock-travel for finer LSB resolution.
				if len(s.ShockTravel) != n {
					s.ShockTravel = make([]float64, n)
					for i := 0; i < n; i++ {
						s.ShockTravel[i] = linkage.WheelToDamperTravel(s.Travel[i])
					}
				}
				smoothedWheel, smoothErr = smoothedRearWheelTravel(s.ShockTravel, whs, linkage)
			} else {
				// Front: smooth wheel-travel directly (head-angle factor is linear).
				smoothedWheel, smoothErr = whs.Smooth(s.Travel)
			}
			if smoothErr == nil {
				vel, err := calculateDerivative(smoothedWheel, sampleRate)
				if err == nil {
					s.Velocity = vel
				} else {
					s.Velocity = make([]float64, n)
				}
			} else {
				s.Velocity = make([]float64, n)
			}
		} else {
			s.Velocity = make([]float64, n)
		}
	} else {
		s.Velocity = make([]float64, n)
	}

	// Digitize velocity
	vbins, dv := digitizeVelocity(s.Velocity, VELOCITY_HIST_STEP)
	s.VelocityBins = vbins
	vbinsFine, dvFine := digitizeVelocity(s.Velocity, VELOCITY_HIST_STEP_FINE)
	s.FineVelocityBins = vbinsFine

	// Strokes
	currentStrokes := filterStrokes(s.Velocity, s.Travel, maxTravel, sampleRate, velocityZeroThreshold)
	s.Strokes.categorize(currentStrokes, s.Travel, maxTravel)
	if len(s.Strokes.Compressions) == 0 && len(s.Strokes.Rebounds) == 0 {
		s.Present = false
	} else {
		s.Strokes.digitize(dt, dv, dvFine)
	}
}

type UuidExt struct{}

func (x UuidExt) WriteExt(v interface{}) []byte {
	v2 := v.(*uuid.UUID)
	return []byte(v2.String())
}

func (x UuidExt) ReadExt(dst interface{}, src []byte) {
	tt := dst.(*uuid.UUID)
	*tt = uuid.MustParse(string(src))
}

func newMsgpackHandle() *codec.MsgpackHandle {
	var h codec.MsgpackHandle
	h.SetBytesExt(reflect.TypeOf(uuid.UUID{}), 1, UuidExt{})
	return &h
}

// ReprocessVelocityFromBlob deserializes an existing Processed blob,
// recomputes velocity-dependent data if needed, and returns the updated blob.
func ReprocessVelocityFromBlob(raw []byte) ([]byte, error) {
	h := newMsgpackHandle()

	var pd Processed
	dec := codec.NewDecoderBytes(raw, h)
	if err := dec.Decode(&pd); err != nil {
		return nil, fmt.Errorf("decode session blob: %w", err)
	}

	if pd.ProcessingVersion >= CurrentProcessingVersion {
		return raw, nil
	}

	// Reprocess decoded a stored Linkage that has the polynomial coefficients but not
	// the *polygo.RealPolynomial instance — rebuild it from the coefficients first.
	if len(pd.Linkage.ShockWheelCoeffs) > 0 && pd.Linkage.polynomial == nil {
		pd.Linkage.polynomial, _ = polygo.NewRealPolynomial(pd.Linkage.ShockWheelCoeffs)
	}

	if pd.Front.Present {
		reprocessSuspension(&pd.Front, pd.SampleRate, pd.Linkage.MaxFrontTravel,
			forkVelocityZeroThreshold(pd.SampleRate), nil)
	}
	if pd.Rear.Present {
		reprocessSuspension(&pd.Rear, pd.SampleRate, pd.Linkage.MaxRearTravel,
			shockVelocityZeroThreshold(pd.SampleRate), &pd.Linkage)
	}
	pd.airtimes()
	pd.ProcessingVersion = CurrentProcessingVersion

	var out []byte
	enc := codec.NewEncoderBytes(&out, h)
	if err := enc.Encode(&pd); err != nil {
		return nil, fmt.Errorf("encode session blob: %w", err)
	}
	return out, nil
}
