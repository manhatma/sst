package psst

import (
	"math"
	"testing"

	"github.com/SeanJxie/polygo"
)

func linkageWithPolynomial(t *testing.T, coefficients []float64) *Linkage {
	t.Helper()
	polynomial, err := polygo.NewRealPolynomial(coefficients)
	if err != nil {
		t.Fatalf("create polynomial: %v", err)
	}
	return &Linkage{polynomial: polynomial}
}

func TestRearWheelVelocityZeroThresholdUsesLeverageAtMedianShock(t *testing.T) {
	// wheel = shock + shock^2, so dWheel/dShock = 1 + 2*shock.
	linkage := linkageWithPolynomial(t, []float64{0, 1, 1})
	shockTravel := []float64{3, 1, 2}
	got := rearWheelVelocityZeroThreshold(0.01, 100, linkage, shockTravel, nil)
	want := shockVelocityZeroThreshold(0.01, 100) * 5
	if math.Abs(got-want) > 1e-12 {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestRearWheelVelocityZeroThresholdGuardsInvalidLeverage(t *testing.T) {
	shockDeadBand := shockVelocityZeroThreshold(0.01, 100)
	tests := []struct {
		name         string
		coefficients []float64
		shockTravel  []float64
	}{
		{name: "greater than ten", coefficients: []float64{0, 11}, shockTravel: []float64{1}},
		{name: "non-positive", coefficients: []float64{0, -1}, shockTravel: []float64{1}},
		{name: "NaN", coefficients: []float64{0, 1, 1}, shockTravel: []float64{1, math.NaN(), 3}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			linkage := linkageWithPolynomial(t, test.coefficients)
			got := rearWheelVelocityZeroThreshold(0.01, 100, linkage, test.shockTravel, nil)
			if got != shockDeadBand {
				t.Fatalf("got %v, want plain shock dead band %v", got, shockDeadBand)
			}
		})
	}
}

func TestRearWheelVelocityZeroThresholdAveragesEvenMedian(t *testing.T) {
	// Median is (2 + 4) / 2 = 3, giving derivative 1 + 2*3 = 7.
	linkage := linkageWithPolynomial(t, []float64{0, 1, 1})
	shockTravel := []float64{6, 2, 4, 0}
	got := rearWheelVelocityZeroThreshold(0.01, 100, linkage, shockTravel, nil)
	want := shockVelocityZeroThreshold(0.01, 100) * 7
	if math.Abs(got-want) > 1e-12 {
		t.Fatalf("got %v, want %v", got, want)
	}
}
