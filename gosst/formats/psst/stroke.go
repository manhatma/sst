package psst

import (
	"math"
	"sort"

	"gonum.org/v1/gonum/floats"
)

type strokestat struct {
	SumTravel                float64
	MaxTravel                float64
	P95Travel                float64
	SumVelocity              float64
	MaxVelocity              float64
	P95VelocityCompression   float64
	P95VelocityRebound       float64
	Bottomouts               int
	Count                    int
}

type stroke struct {
	Start                 int
	End                   int
	Stat                  strokestat
	DigitizedTravel       []int
	DigitizedVelocity     []int
	FineDigitizedVelocity []int
	length                float64
	duration              float64
	airCandidate          bool
}

type strokes struct {
	Compressions []*stroke
	Rebounds     []*stroke
	idlings      []*stroke
}

type airtime struct {
	Start float64
	End   float64
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func sign(v float64) int8 {
	if math.Abs(v) <= VELOCITY_ZERO_THRESHOLD {
		return 0
	} else if math.Signbit(v) {
		return -1
	} else {
		return 1
	}
}

func digitize(data, bins []float64) []int {
	inds := make([]int, len(data))
	for k, v := range data {
		i := sort.SearchFloat64s(bins, v)
		if i == len(bins) || (i > 0 && v < bins[i]) {
			i -= 1
		}
		if i < 0 {
			i = 0
		} else if i >= len(bins)-1 && len(bins) > 1 {
			i = len(bins) - 2
		} else if len(bins) == 1 {
			i = 0
		}
		inds[k] = i
	}
	return inds
}

func digitizeVelocity(v []float64, step float64) (bins []float64, data []int) {
	if len(v) == 0 {
		return []float64{}, []int{}
	}
	minVal := floats.Min(v)
	maxVal := floats.Max(v)

	// 0 lies on a bin edge — negative and positive velocities get separate bins
	mn := math.Floor(minVal/step) * step
	mx := (math.Floor(maxVal/step) + 1) * step
	if mx <= mn {
		mx = mn + step
	}

	numBins := int((mx-mn)/step) + 1
	if numBins <= 0 {
		numBins = 1
	}

	bins = linspace(mn, mx, numBins)
	if len(bins) == 0 {
		return []float64{mn}, digitize(v, []float64{mn})
	}
	data = digitize(v, bins)
	return bins, data
}

func (this *stroke) overlaps(other *stroke) bool {
	l := max(this.End-this.Start, other.End-other.Start)
	if l == 0 {
		return false
	}
	s := max(this.Start, other.Start)
	e := min(this.End, other.End)
	overlapDuration := e - s
	if overlapDuration < 0 {
		overlapDuration = 0
	}
	return float32(overlapDuration) >= AIRTIME_OVERLAP_THRESHOLD*float32(l)
}

// getPercentileValue matches MathNet.Numerics' Percentile/QuantileInplace (the
// R-8 "median-unbiased" estimator h = (n + 1/3)*tau + 1/3 with linear
// interpolation) so gosst's stored percentiles match Sufni.Bridge. tau is a
// fraction in [0, 1].
func getPercentileValue(values []float64, tau float64) float64 {
	n := len(values)
	if n == 0 {
		return 0.0
	}

	sortedValues := append([]float64(nil), values...)
	sort.Float64s(sortedValues)

	if tau <= 0.0 || n == 1 {
		return sortedValues[0]
	}
	if tau >= 1.0 {
		return sortedValues[n-1]
	}

	h := (float64(n)+1.0/3.0)*tau + 1.0/3.0
	hf := int(math.Floor(h))
	lo := hf - 1
	if lo < 0 {
		lo = 0
	} else if lo > n-1 {
		lo = n - 1
	}
	hi := hf
	if hi < 0 {
		hi = 0
	} else if hi > n-1 {
		hi = n - 1
	}

	return sortedValues[lo] + (h-float64(hf))*(sortedValues[hi]-sortedValues[lo])
}

func newStroke(start, end int, duration float64, travel, velocity []float64, maxTravel float64) *stroke {
	s := &stroke{
		Start:    start,
		End:      end,
		length:   travel[end] - travel[start],
		duration: duration,
	}

	velSubSlice := velocity[start : end+1]
	travelSubSlice := travel[start : end+1]

	var mv float64
	if len(velSubSlice) > 0 {
		if s.length < 0 {
			mv = floats.Min(velSubSlice)
		} else {
			mv = floats.Max(velSubSlice)
		}
	}

	bo := 0
	for i := start; i <= end; {
		if travel[i] > maxTravel-BOTTOMOUT_THRESHOLD {
			bo++
			
			for ; i <= end && travel[i] > maxTravel-BOTTOMOUT_THRESHOLD; i++ {
			}
		} else {
			i++
		}
	}


	p95t := getPercentileValue(travelSubSlice, 0.95)

	var compVelocities []float64
	for _, v := range velSubSlice {
		if v > 0 {
			compVelocities = append(compVelocities, v)
		}
	}
	p95Comp := getPercentileValue(compVelocities, 0.95)

	var rebMagnitudes []float64
	for _, v := range velSubSlice {
		if v < 0 {
			rebMagnitudes = append(rebMagnitudes, -v)
		}
	}
	p95Reb := getPercentileValue(rebMagnitudes, 0.95)

	var sumTravel float64
	if len(travelSubSlice) > 0 {
		sumTravel = floats.Sum(travelSubSlice)
	}
	var maxActualTravel float64
	if len(travelSubSlice) > 0 {
		maxActualTravel = floats.Max(travelSubSlice)
	}
	var sumVelocity float64
	if len(velSubSlice) > 0 {
		sumVelocity = floats.Sum(velSubSlice)
	}


	stat := strokestat{
		SumTravel:              sumTravel,
		MaxTravel:              maxActualTravel,
		P95Travel:              p95t,
		SumVelocity:            sumVelocity,
		MaxVelocity:            mv,
		P95VelocityCompression: p95Comp,
		P95VelocityRebound:     p95Reb,
		Bottomouts:             bo,
		Count:                  end - start + 1,
	}
	s.Stat = stat
	return s
}

func (this *strokes) categorize(strokes []*stroke, travel []float64, maxTravel float64) {
	this.Compressions = make([]*stroke, 0)
	this.Rebounds = make([]*stroke, 0)
	this.idlings = make([]*stroke, 0)

	for i, currentStroke := range strokes {
		if math.Abs(currentStroke.length) < STROKE_LENGTH_THRESHOLD &&
			currentStroke.duration >= IDLING_DURATION_THRESHOLD {

			if i > 0 && i < len(strokes)-1 &&
				currentStroke.Stat.MaxTravel <= AIRTIME_TRAVEL_THRESHOLD &&
				currentStroke.duration >= AIRTIME_DURATION_THRESHOLD &&
				strokes[i+1].Stat.MaxVelocity >= AIRTIME_VELOCITY_THRESHOLD {
				currentStroke.airCandidate = true
			}
			this.idlings = append(this.idlings, currentStroke)
		} else if currentStroke.length >= STROKE_LENGTH_THRESHOLD {
			this.Compressions = append(this.Compressions, currentStroke)
		} else if currentStroke.length <= -STROKE_LENGTH_THRESHOLD {
			this.Rebounds = append(this.Rebounds, currentStroke)
		}
	}
}

func (this *strokes) digitize(dt, dv, dvFine []int) {
	for _, s := range this.Compressions {
		if s.Start <= s.End && s.End < len(dt) && s.End < len(dv) && s.End < len(dvFine) {
			s.DigitizedTravel = dt[s.Start : s.End+1]
			s.DigitizedVelocity = dv[s.Start : s.End+1]
			s.FineDigitizedVelocity = dvFine[s.Start : s.End+1]
		}
	}
	for _, s := range this.Rebounds {
		if s.Start <= s.End && s.End < len(dt) && s.End < len(dv) && s.End < len(dvFine) {
			s.DigitizedTravel = dt[s.Start : s.End+1]
			s.DigitizedVelocity = dv[s.Start : s.End+1]
			s.FineDigitizedVelocity = dvFine[s.Start : s.End+1]
		}
	}
}

func filterStrokes(velocity, travel []float64, maxTravel float64, rate uint16) (strokes []*stroke) {
	if len(velocity) == 0 || float64(rate) == 0 {
		return []*stroke{}
	}

	var startIndex int
	var startSign int8

	for i := 0; i < len(velocity); { 
		startIndex = i
		startSign = sign(velocity[i])

		segmentEndIndex := i
		for ; segmentEndIndex < len(velocity)-1 && sign(velocity[segmentEndIndex+1]) == startSign; segmentEndIndex++ {
		}

		d := float64(segmentEndIndex-startIndex+1) / float64(rate)

		currentSegmentMaxTravel := 0.0
		if startIndex <= segmentEndIndex && segmentEndIndex < len(travel) {
			subTravel := travel[startIndex : segmentEndIndex+1]
			if len(subTravel) > 0 {
				currentSegmentMaxTravel = floats.Max(subTravel)
			}
		}


		if currentSegmentMaxTravel < STROKE_LENGTH_THRESHOLD*STROKE_LENGTH_THRESHOLD_FAC &&
			len(strokes) > 0 &&
			strokes[len(strokes)-1].Stat.MaxTravel < STROKE_LENGTH_THRESHOLD*STROKE_LENGTH_THRESHOLD_FAC {

			prev := strokes[len(strokes)-1]
			strokes[len(strokes)-1] = newStroke(prev.Start, segmentEndIndex, prev.duration+d, travel, velocity, maxTravel)

		} else {
			s := newStroke(startIndex, segmentEndIndex, d, travel, velocity, maxTravel)
			strokes = append(strokes, s)
		}

		i = segmentEndIndex + 1
	}
	return strokes
}
