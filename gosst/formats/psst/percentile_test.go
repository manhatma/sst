package psst

import (
	"math"
	"testing"
)

func gen(n int) []float64 {
	a := make([]float64, n)
	for i := 0; i < n; i++ {
		a[i] = math.Sin(float64(i)*0.7)*100.0 + float64(i)*0.13 + float64(i%17)*3.1
	}
	return a
}

// Reference values from MathNet.Numerics 6.0.0-beta2 .Percentile(95).
func TestGetPercentileValueMatchesMathNet(t *testing.T) {
	cases := map[int]float64{
		5:      105.00497299884603,
		10:     105.00497299884603,
		11:     105.00497299884603,
		100:    137.06464013449693,
		159114: 19675.27644310718,
	}
	for n, want := range cases {
		got := getPercentileValue(gen(n), 0.95)
		if math.Abs(got-want) > 1e-9 {
			t.Fatalf("n=%d: got %.12f, want %.12f", n, got, want)
		}
	}
}
