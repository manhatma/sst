package psst

import (
	"bufio"
	"errors"
	"fmt"
	"math"
	"strings"

	"github.com/SeanJxie/polygo"
	"github.com/google/uuid"
	"github.com/openacid/slimarray/polyfit"
	"gonum.org/v1/gonum/floats"
	"golang.org/x/exp/constraints"
)

const (
	VELOCITY_ZERO_THRESHOLD             = 0.02	// (mm/s) maximum velocity to be considered as zero
	IDLING_DURATION_THRESHOLD           = 0.10	// (s) minimum duration to consider stroke an idle period
	AIRTIME_TRAVEL_THRESHOLD            = 3		// (mm) maximum travel to consider stroke an airtime
	AIRTIME_DURATION_THRESHOLD          = 0.20	// (s) minimum duration to consider stroke an airtime
	AIRTIME_VELOCITY_THRESHOLD          = 500	// (mm/s) minimum velocity after stroke to consider it an airtime
	AIRTIME_OVERLAP_THRESHOLD           = 0.5	// f&r airtime candidates must overlap at least this amount to be an airtime
	AIRTIME_TRAVEL_MEAN_THRESHOLD_RATIO = 0.04	// stroke f&r mean travel must be below max*this to be an airtime
	STROKE_LENGTH_THRESHOLD             = 1.5 	// (mm) minimum length to consider stroke a compression/rebound
	TRAVEL_HIST_BINS                    = 40	// number of travel histogram bins
	VELOCITY_HIST_TRAVEL_BINS           = 10	// number of travel histogram bins for velocity histogram
	VELOCITY_HIST_STEP                  = 100.0	// (mm/s) step between velocity histogram bins
	VELOCITY_HIST_STEP_FINE             = 15.0	// (mm/s) step between fine-grained velocity histogram bins
	BOTTOMOUT_THRESHOLD                 = 2.5	// (mm) bottomouts are regions where travel > max_travel - this value

	// Whittaker-Henderson Smoother specific parameters:  
	// (Schmid, M., Rath, D., & Diebold, U. (2022). Why and How Savitzky-Golay
	// Filters Should Be Replaced. ACS Measurement Science Au, 2, 185-196.
	// Chapter 2.4. Replacing SG Filters, Eq. 14)    
	//
	// ~27 Hz -3dB cutoff based on original Savitzky-Golay filter parameters (51, 1, 3) at 1 kHz sample rate.
	// Translates to: WH_ORDER = 2, WH_LAMBDA = 272 for equivalent smoothing characteristics.

	WH_ORDER  = 2

	// f_cutoff    WH_LAMBDA	 FWHM for 95%	 
	//  (-3dB)                     fidelity
	//                              @860SPS	
	// 10.0 Hz	       14.600	  65 Samples
	// 12.5 Hz	        5.900	  52 Samples
	// 15.0 Hz	        2.900	  43 Samples
	// 17.5 Hz	        1.550	  37 Samples
	// 20.0 Hz	          920	  32 Samples
	// 22.5 Hz	          580	  29 Samples
	// 25.0 Hz	          380	  26 Samples
	// 27.1 Hz	          272	  24 Samples	<-- ~original SG-Filter
	// 27.5 Hz	          260	  23 Samples
	// 30.0 Hz	          185	  21 Samples
	// 32.5 Hz	          130	  20 Samples
	// 35.0 Hz	          100	  18 Samples
	// 37.5 Hz	           75	  17 Samples
	// 40.0 Hz	           60	  16 Samples
	WH_LAMBDA = 260

	// Suspension dynamics are in the 0–10 Hz band. 
	// Using a cutoff near 2.5-3× (27.5 Hz) maintains signal integrity 
	// while providing sufficient attenuation of high-frequency noise.
	// Balances fidelity and noise suppression without over-filtering.
)

// calculateDerivative computes the derivative using central differences for interior points,
// and forward/backward differences for boundary points.
func calculateDerivative(data []float64, sampleRate uint16) ([]float64, error) {
	n := len(data)
	if n == 0 {
		return []float64{}, nil
	}
	if sampleRate == 0 {
		return nil, errors.New("SampleRate darf für die Ableitungsberechnung nicht Null sein")
	}
	if n < 2 && n > 0 {
		derivative := make([]float64, n)
		derivative[0] = 0
		return derivative, nil
	}
	if n < 1 { // Sollte bereits durch n==0 abgedeckt sein
		return []float64{}, nil
	}

	dt := 1.0 / float64(sampleRate)
	derivative := make([]float64, n)

	// Sicherstellen, dass data[1] existiert
	if n > 1 {
		derivative[0] = (data[1] - data[0]) / dt
	} else { // Nur ein Punkt, Ableitung ist 0
		derivative[0] = 0
		return derivative, nil // Frühzeitiger Ausstieg, da keine weiteren Berechnungen möglich
	}

	for i := 1; i < n-1; i++ {
		derivative[i] = (data[i+1] - data[i-1]) / (2 * dt)
	}
	// Sicherstellen, dass data[n-2] existiert (n > 1 bereits geprüft)
	derivative[n-1] = (data[n-1] - data[n-2]) / dt

	return derivative, nil
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
	Front    suspension
	Rear     suspension
	Linkage  Linkage
	Airtimes []*airtime

func (this *Linkage) ProcessRawData() error {
	var records []LinkageRecord
	scanner := bufio.NewScanner(strings.NewReader(this.RawData))
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
			s += 1.0 / l
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
	this.polynomial, _ = polygo.NewRealPolynomial(this.ShockWheelCoeffs)
	this.MaxRearTravel = this.polynomial.At(this.MaxRearStroke)
	this.MaxFrontTravel = math.Sin(this.HeadAngle*math.Pi/180.0) * this.MaxFrontStroke
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

		currentStrokes := filterStrokes(pd.Front.Velocity, pd.Front.Travel, pd.Linkage.MaxFrontTravel, pd.Meta.SampleRate)
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
		for idx, value := range rear {
			out, _ := pd.Rear.Calibration.Evaluate(float64(value))
			x := pd.Linkage.polynomial.At(out)
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
				smoothedTravel, errSmooth := whsRear.Smooth(pd.Rear.Travel)
				if errSmooth == nil {
					velocity, errVel := calculateDerivative(smoothedTravel, pd.Meta.SampleRate)
					if errVel == nil {
						pd.Rear.Velocity = velocity
					} else {
						fmt.Printf("Warning: Error calculating rear velocity: %v. Using zero velocity instead.\n", errVel)
						pd.Rear.Velocity = make([]float64, rc)
					}
				} else {
					fmt.Printf("Warning: Error smoothing rear travel data: %v. Using zero velocity instead.\n", errSmooth)
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

		currentStrokes := filterStrokes(pd.Rear.Velocity, pd.Rear.Travel, pd.Linkage.MaxRearTravel, pd.Meta.SampleRate)
		pd.Rear.Strokes.categorize(currentStrokes, pd.Rear.Travel, pd.Linkage.MaxRearTravel)
		if len(pd.Rear.Strokes.Compressions) == 0 && len(pd.Rear.Strokes.Rebounds) == 0 {
			pd.Rear.Present = false
		} else {
			// pd.Rear.Strokes.digitizeVelocity(dv, dvFine) // legacy call
			pd.Rear.Strokes.digitize(dtRear, dv, dvFine)
		}
	}

	pd.airtimes()
	return &pd, nil
}
