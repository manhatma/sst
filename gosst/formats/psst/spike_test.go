package psst

import (
	"math"
	"testing"
)

// A single-sample spike whose implied jerk exceeds the limit must be replaced
// by the neighbour interpolation; a smooth ramp must be left untouched.
func TestRejectSingleSampleSpikes(t *testing.T) {
	rate := uint16(860)
	dt := 1.0 / float64(rate)
	floor := 0.5 * SPIKE_JERK_LIMIT * dt * dt // ~3382 mm/s @ 860 SPS

	// smooth ramp: no spike -> unchanged
	ramp := []float64{0, 100, 200, 300, 400}
	cp := append([]float64(nil), ramp...)
	rejectSingleSampleSpikes(cp, rate)
	for i := range ramp {
		if math.Abs(cp[i]-ramp[i]) > 1e-9 {
			t.Fatalf("ramp modified at %d: %v != %v", i, cp[i], ramp[i])
		}
	}

	// isolated spike well above the floor -> replaced by mean of neighbours
	v := []float64{100, 100, 100 + floor*2, 100, 100}
	rejectSingleSampleSpikes(v, rate)
	if math.Abs(v[2]-100.0) > 1e-9 {
		t.Fatalf("spike not rejected: got %v, want 100", v[2])
	}

	// borderline deviation just below the floor -> kept
	v2 := []float64{100, 100, 100 + floor*0.5, 100, 100}
	want := 100 + floor*0.5
	rejectSingleSampleSpikes(v2, rate)
	if math.Abs(v2[2]-want) > 1e-9 {
		t.Fatalf("sub-threshold value wrongly rejected: got %v, want %v", v2[2], want)
	}
}
