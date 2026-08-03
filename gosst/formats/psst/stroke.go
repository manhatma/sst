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
	Idlings      []*stroke

	// airCandidates and topOut are airtime-detection working state, unexported so
	// the msgpack codec skips them (mirrors Sufni.Bridge's [IgnoreMember] on
	// AirCandidates/TopOut) -- they are cheap to recompute from Compressions/
	// Rebounds/Idlings and travel on every categorize() call and have no business
	// surviving a round-trip through storage.
	airCandidates []*stroke
	topOut        float64
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

func sign(v, velocityZeroThreshold float64) int8 {
	if math.Abs(v) <= velocityZeroThreshold {
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

// overlaps compares the shared span against the SHORTER of the two strokes, not the
// longer one: a fork typically snaps to top-out while the shock creeps there over a
// longer interval, so front and rear hover strokes for the same jump routinely differ
// 2-3x in length. Gating on the longer stroke made such a pair fail to match, so the
// same jump fell through to the single-sided fallback on each side and got reported
// twice; coveredByAirtime() is the dedup guard that backs this up for the fallback path.
// l == 0 is unreachable for real candidates: a 1-sample stroke can never reach
// AIRTIME_DURATION_THRESHOLD, so no early-out for it is needed here (matching C#,
// which has none and would return true for a degenerate zero-length pair).
func (this *stroke) overlaps(other *stroke) bool {
	l := float64(min(this.End-this.Start, other.End-other.Start))
	s := max(this.Start, other.Start)
	e := min(this.End, other.End)
	overlapDuration := float64(e - s)
	return overlapDuration >= AIRTIME_OVERLAP_THRESHOLD*l
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

// estimateTopOut replaces the old fixed "travel == 0 is top-out" assumption. Calibration
// offsets, coil preload, top-out bumpers and (for the rear) the shock->wheel polynomial
// all shift the fully-extended reading away from zero -- measured as much as a few mm on
// real bikes -- so a fixed absolute threshold made some perfectly normal shocks
// structurally ineligible for airtime detection. Instead this takes a low quantile of the
// travel distribution as the session's own top-out reading, which self-calibrates to
// whatever offset that particular suspension actually rests at. The quantile is capped as
// a fraction of maxTravel so a session with almost no genuine rest samples (e.g. a very
// short, all-action clip) can't have the quantile land on a real stroke and be mistaken
// for top-out.
func estimateTopOut(travel []float64, maxTravel float64) float64 {
	if len(travel) == 0 {
		return 0
	}

	sorted := make([]float64, 0, len(travel))
	for _, t := range travel {
		if !math.IsNaN(t) {
			sorted = append(sorted, t)
		}
	}
	if len(sorted) == 0 {
		return 0
	}
	sort.Float64s(sorted)

	n := len(sorted)
	idx := TOP_OUT_QUANTILE * float64(n-1)
	if idx < 0 {
		idx = 0
	} else if idx > float64(n-1) {
		idx = float64(n - 1)
	}
	index := int(idx)

	v := sorted[index]
	topOutCap := maxTravel * TOP_OUT_MAX_RATIO
	// A degenerate linkage (negative MaxTravel) would make the cap negative and
	// leak a negative top-out into every downstream threshold. C#'s Math.Clamp
	// throws on min>max; here we keep the pipeline alive by pinning the cap to 0,
	// which is a no-op for every physical (non-negative) MaxTravel.
	if topOutCap < 0 {
		topOutCap = 0
	}
	if v < 0 {
		v = 0
	} else if v > topOutCap {
		v = topOutCap
	}
	return v
}

func isSettledSample(travel, velocity, topOut, maxTravel float64) bool {
	return travel-topOut <= AIRTIME_SETTLED_TRAVEL_RATIO*maxTravel &&
		math.Abs(velocity) <= AIRTIME_QUIESCENT_VELOCITY
}

// settledSampleFraction returns the fraction of all samples in s that are settled.
// Unlike restsAtTopOut, it does not require a contiguous run.
func settledSampleFraction(travel, velocity []float64, s *stroke, topOut, maxTravel float64) float64 {
	settled := 0
	for i := s.Start; i <= s.End; i++ {
		if isSettledSample(travel[i], velocity[i], topOut, maxTravel) {
			settled++
		}
	}
	return float64(settled) / float64(s.End-s.Start+1)
}

func (this *strokes) categorize(strokes []*stroke, travel, velocity []float64, maxTravel float64) {
	this.Compressions = make([]*stroke, 0)
	this.Rebounds = make([]*stroke, 0)
	this.Idlings = make([]*stroke, 0)
	this.airCandidates = make([]*stroke, 0)

	this.topOut = estimateTopOut(travel, maxTravel)

	// Below this travel a stroke is close enough to topOut to be a plausible airtime
	// hover; the fixed AIRTIME_TRAVEL_THRESHOLD and the maxTravel-relative
	// AIRTIME_TRAVEL_THRESHOLD_RATIO are both present because a purely relative gate
	// is too tight on small-travel setups and a purely fixed one is too tight on
	// long-travel ones -- the larger of the two always applies.
	airtimeTravelThreshold := this.topOut + math.Max(AIRTIME_TRAVEL_THRESHOLD, AIRTIME_TRAVEL_THRESHOLD_RATIO*maxTravel)

	for i, currentStroke := range strokes {
		// Air-candidate test: independent of, and evaluated before, the
		// comp/rebound/idling split below -- a stroke can be a plausible airtime
		// hover regardless of which of those three buckets it lands in.
		// stroke.length alone can't distinguish a hover from stiction creep, so the
		// allowed |length| grows with the stroke's own duration (AIRTIME_CREEP_RATE);
		// a stroke settled for virtually its whole duration waives that creep budget.
		// AIRTIME_DURATION_MAX rejects hovers long enough to be a bike being carried
		// or leaned rather than genuinely airborne; and the following stroke's peak
		// velocity must show a real landing impact, not just quiet settling.
		if i > 0 && i < len(strokes)-1 &&
			currentStroke.duration >= AIRTIME_DURATION_THRESHOLD &&
			currentStroke.duration <= AIRTIME_DURATION_MAX &&
			(math.Abs(currentStroke.length) <= STROKE_LENGTH_THRESHOLD+AIRTIME_CREEP_RATE*currentStroke.duration ||
				settledSampleFraction(travel, velocity, currentStroke, this.topOut, maxTravel) >= AIRTIME_CREEP_WAIVER_SETTLED_FRACTION) &&
			currentStroke.Stat.SumTravel/float64(currentStroke.Stat.Count) <= airtimeTravelThreshold &&
			strokes[i+1].Stat.MaxVelocity >= AIRTIME_VELOCITY_THRESHOLD {
			currentStroke.airCandidate = true
			this.airCandidates = append(this.airCandidates, currentStroke)
		}

		if math.Abs(currentStroke.length) < STROKE_LENGTH_THRESHOLD {
			this.Idlings = append(this.Idlings, currentStroke)
		} else if currentStroke.length >= STROKE_LENGTH_THRESHOLD {
			this.Compressions = append(this.Compressions, currentStroke)
		} else {
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
	for _, s := range this.Idlings {
		if s.Start <= s.End && s.End < len(dt) && s.End < len(dv) && s.End < len(dvFine) {
			s.DigitizedTravel = dt[s.Start : s.End+1]
			s.DigitizedVelocity = dv[s.Start : s.End+1]
			s.FineDigitizedVelocity = dvFine[s.Start : s.End+1]
		}
	}
}

func filterStrokes(velocity, travel []float64, maxTravel float64, rate uint16, velocityZeroThreshold float64) (strokes []*stroke) {
	if len(velocity) == 0 || float64(rate) == 0 {
		return []*stroke{}
	}

	var startIndex int
	var startSign int8

	for i := 0; i < len(velocity); { 
		startIndex = i
		startSign = sign(velocity[i], velocityZeroThreshold)

		segmentEndIndex := i
		for segmentEndIndex < len(velocity)-1 {
			nextSign := sign(velocity[segmentEndIndex+1], velocityZeroThreshold)
			if nextSign != 0 && nextSign != startSign {
				break
			}
			segmentEndIndex++
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
