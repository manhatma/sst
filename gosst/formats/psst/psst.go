package psst

import (
	"bufio"
	"errors" // Beibehalten für andere Fehler
	"fmt"    // Beibehalten für Formatierung
	"math"
	"strings"

	"github.com/SeanJxie/polygo"
	"github.com/google/uuid"
	"github.com/openacid/slimarray/polyfit"
	// Savitzky-Golay Import wurde bereits entfernt
	"gonum.org/v1/gonum/floats" // Für globale Statistiken
	"golang.org/x/exp/constraints"
)

const (
	VELOCITY_ZERO_THRESHOLD             = 0.02
	IDLING_DURATION_THRESHOLD           = 0.01
	AIRTIME_TRAVEL_THRESHOLD            = 15 // 3
	AIRTIME_DURATION_THRESHOLD          = 0.20
	AIRTIME_VELOCITY_THRESHOLD          = 500
	AIRTIME_OVERLAP_THRESHOLD           = 0.5
	AIRTIME_TRAVEL_MEAN_THRESHOLD_RATIO = 0.1 // 0.04
	STROKE_LENGTH_THRESHOLD             = 5 // 2.5 // 1.25 // 5
	TRAVEL_HIST_BINS                    = 40
	VELOCITY_HIST_TRAVEL_BINS           = 10
	VELOCITY_HIST_STEP                  = 100.0
	VELOCITY_HIST_STEP_FINE             = 15.0
	BOTTOMOUT_THRESHOLD                 = 3

	// Anwendungsspezifische Parameter für den Whittaker-Henderson Smoother:
	// -3dB-Grenzfrequenz wie der ursprüngliche Savitzky-Golay-Filter mit 
	// den Parametern (51, 1, 3). 
	// (Schmid, M., Rath, D., & Diebold, U. (2022). Why and How Savitzky-Golay
	// Filters Should Be Replaced. ACS Measurement Science Au, 2, 185-196.
	// Chapter 2.4. Replacing SG Filters, Eq. 14)    
	// WH_ORDER  = 2
	// WH_LAMBDA = 500
	WH_ORDER  = 2
	// entspricht ca. 95% Fidelity für FWHM von ca. 21 Samples; -3dB bei ca. 31 Hz
	WH_LAMBDA = 5000
)

// calculateDerivative berechnet die Ableitung mittels zentraler Differenzen für innere Punkte
// und Vorwärts-/Rückwärtsdifferenzen für Randpunkte.
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
	Calibration            Calibration // Definiert in calibration.go
	Travel                 []float64
	Velocity               []float64
	Strokes                strokes     // Definiert in stroke.go
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
	FrontCalibration *Calibration // Definiert in calibration.go
	RearCalibration  *Calibration // Definiert in calibration.go
}

type Processed struct {
	Meta
	Front    suspension
	Rear     suspension
	Linkage  Linkage
	Airtimes []*airtime // airtime definiert in stroke.go, Methode airtimes in airtimes.go
}

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

// RecordCountMismatchError wird in der aktuellen Logik nicht explizit verwendet, wenn WH eingesetzt wird,
// da Front und Rear unabhängig geglättet werden können.
// type RecordCountMismatchError struct{}
// func (e *RecordCountMismatchError) Error() string { return "Anzahl der Front- und Rear-Records ist nicht gleich" }

func ProcessRecording[T Number](front, rear []T, meta Meta, setup *SetupData) (*Processed, error) {
	var pd Processed
	pd.Meta = meta
	// Calibration wird von setup.FrontCalibration zugewiesen, dessen Typ aus calibration.go stammt
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
			out, _ := pd.Front.Calibration.Evaluate(float64(value)) // Evaluate von calibration.go
			x := out * front_coeff
			x = math.Max(0, x)
			x = math.Min(x, pd.Linkage.MaxFrontTravel)
			pd.Front.Travel[idx] = x
		}

		if len(pd.Front.Travel) > 0 {
			pd.Front.GlobalMaxTravelAllData = floats.Max(pd.Front.Travel)
			pd.Front.GlobalP95TravelAllData = getPercentileValue(pd.Front.Travel, 0.95) // von stroke.go
			pd.Front.GlobalAvgTravelAllData = floats.Sum(pd.Front.Travel) / float64(len(pd.Front.Travel))
		}

		var dtFront []int
		if pd.Linkage.MaxFrontTravel > 0 {
			tbins := linspace(0, pd.Linkage.MaxFrontTravel, TRAVEL_HIST_BINS+1)
			dtFront = digitize(pd.Front.Travel, tbins) // von stroke.go
			pd.Front.TravelBins = tbins
		} else {
			pd.Front.TravelBins = []float64{}
			dtFront = make([]int, fc)
		}
		// pd.Front.Strokes.digitizeTravel(dtFront) // Veralteter Aufruf

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
						fmt.Printf("Warnung: Fehler bei der Berechnung der Front-Geschwindigkeit: %v. Null-Geschwindigkeit wird verwendet.\n", errVel)
						pd.Front.Velocity = make([]float64, fc)
					}
				} else {
					fmt.Printf("Warnung: Fehler beim Glätten des Front-Federwegs: %v. Null-Geschwindigkeit wird verwendet.\n", errSmooth)
					pd.Front.Velocity = make([]float64, fc)
				}
			} else {
				fmt.Printf("Warnung: Fehler beim Erstellen des Front-WH-Smoothers: %v. Null-Geschwindigkeit wird verwendet.\n", errWhs)
				pd.Front.Velocity = make([]float64, fc)
			}
		} else {
			if fc < minPointsForWH {
				fmt.Printf("Warnung: Front-Datenpunkte (%d) zu wenige für WH-Smoother (min %d für Ordnung %d benötigt). Null-Geschwindigkeit wird verwendet.\n", fc, minPointsForWH, WH_ORDER)
			}
			if pd.Meta.SampleRate == 0 {
				fmt.Printf("Warnung: Front-SampleRate ist Null, Geschwindigkeit kann nicht berechnet werden. Null-Geschwindigkeit wird verwendet.\n")
			}
			pd.Front.Velocity = make([]float64, fc)
		}

		vbins, dv := digitizeVelocity(pd.Front.Velocity, VELOCITY_HIST_STEP) // von stroke.go
		pd.Front.VelocityBins = vbins
		vbinsFine, dvFine := digitizeVelocity(pd.Front.Velocity, VELOCITY_HIST_STEP_FINE) // von stroke.go
		pd.Front.FineVelocityBins = vbinsFine

		currentStrokes := filterStrokes(pd.Front.Velocity, pd.Front.Travel, pd.Linkage.MaxFrontTravel, pd.Meta.SampleRate) // von stroke.go
		pd.Front.Strokes.categorize(currentStrokes, pd.Front.Travel, pd.Linkage.MaxFrontTravel) // von stroke.go

		if len(pd.Front.Strokes.Compressions) == 0 && len(pd.Front.Strokes.Rebounds) == 0 {
			pd.Front.Present = false
		} else {
			// pd.Front.Strokes.digitizeVelocity(dv, dvFine) // Veralteter Aufruf
			pd.Front.Strokes.digitize(dtFront, dv, dvFine) // Korrigierter Aufruf gemäß stroke.go
		}
	}

	if pd.Rear.Present {
		pd.Rear.Travel = make([]float64, rc)
		for idx, value := range rear {
			out, _ := pd.Rear.Calibration.Evaluate(float64(value)) // von calibration.go
			x := pd.Linkage.polynomial.At(out)
			x = math.Max(0, x)
			x = math.Min(x, pd.Linkage.MaxRearTravel)
			pd.Rear.Travel[idx] = x
		}

		if len(pd.Rear.Travel) > 0 {
			pd.Rear.GlobalMaxTravelAllData = floats.Max(pd.Rear.Travel)
			pd.Rear.GlobalP95TravelAllData = getPercentileValue(pd.Rear.Travel, 0.95) // von stroke.go
			pd.Rear.GlobalAvgTravelAllData = floats.Sum(pd.Rear.Travel) / float64(len(pd.Rear.Travel))
		}

		var dtRear []int
		if pd.Linkage.MaxRearTravel > 0 {
			tbins := linspace(0, pd.Linkage.MaxRearTravel, TRAVEL_HIST_BINS+1)
			dtRear = digitize(pd.Rear.Travel, tbins) // von stroke.go
			pd.Rear.TravelBins = tbins
		} else {
			pd.Rear.TravelBins = []float64{}
			dtRear = make([]int, rc)
		}
		// pd.Rear.Strokes.digitizeTravel(dtRear) // Veralteter Aufruf

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
						fmt.Printf("Warnung: Fehler bei der Berechnung der Rear-Geschwindigkeit: %v. Null-Geschwindigkeit wird verwendet.\n", errVel)
						pd.Rear.Velocity = make([]float64, rc)
					}
				} else {
					fmt.Printf("Warnung: Fehler beim Glätten des Rear-Federwegs: %v. Null-Geschwindigkeit wird verwendet.\n", errSmooth)
					pd.Rear.Velocity = make([]float64, rc)
				}
			} else {
				fmt.Printf("Warnung: Fehler beim Erstellen des Rear-WH-Smoothers: %v. Null-Geschwindigkeit wird verwendet.\n", errWhs)
				pd.Rear.Velocity = make([]float64, rc)
			}
		} else {
			if rc < minPointsForWH {
				fmt.Printf("Warnung: Rear-Datenpunkte (%d) zu wenige für WH-Smoother (min %d für Ordnung %d benötigt). Null-Geschwindigkeit wird verwendet.\n", rc, minPointsForWH, WH_ORDER)
			}
			if pd.Meta.SampleRate == 0 {
				fmt.Printf("Warnung: Rear-SampleRate ist Null, Geschwindigkeit kann nicht berechnet werden. Null-Geschwindigkeit wird verwendet.\n")
			}
			pd.Rear.Velocity = make([]float64, rc)
		}

		vbins, dv := digitizeVelocity(pd.Rear.Velocity, VELOCITY_HIST_STEP) // von stroke.go
		pd.Rear.VelocityBins = vbins
		vbinsFine, dvFine := digitizeVelocity(pd.Rear.Velocity, VELOCITY_HIST_STEP_FINE) // von stroke.go
		pd.Rear.FineVelocityBins = vbinsFine

		currentStrokes := filterStrokes(pd.Rear.Velocity, pd.Rear.Travel, pd.Linkage.MaxRearTravel, pd.Meta.SampleRate) // von stroke.go
		pd.Rear.Strokes.categorize(currentStrokes, pd.Rear.Travel, pd.Linkage.MaxRearTravel) // von stroke.go
		if len(pd.Rear.Strokes.Compressions) == 0 && len(pd.Rear.Strokes.Rebounds) == 0 {
			pd.Rear.Present = false
		} else {
			// pd.Rear.Strokes.digitizeVelocity(dv, dvFine) // Veralteter Aufruf
			pd.Rear.Strokes.digitize(dtRear, dv, dvFine) // Korrigierter Aufruf gemäß stroke.go
		}
	}

	pd.airtimes() // Methode von airtimes.go
	return &pd, nil
}
