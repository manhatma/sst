package psst

// coveredByAirtime reports whether stroke s falls within an airtime interval already
// found (in sample time, converted to seconds via sampleRate). It backs the dedup
// between the f&r-paired pass and the single-sided fallback passes below: the paired
// pass runs first and is the more trustworthy signal (both ends agree), so a candidate
// it already consumed must not also be reported by a fallback pass.
func coveredByAirtime(airtimes []*airtime, s *stroke, sampleRate uint16) bool {
	start := float64(s.Start) / float64(sampleRate)
	end := float64(s.End) / float64(sampleRate)
	for _, a := range airtimes {
		if start < a.End && end > a.Start {
			return true
		}
	}
	return false
}

// restsAtTopOut looks for a contiguous run, covering at least AIRTIME_SETTLE_FRACTION of
// the stroke, where travel sits within maxTravel*AIRTIME_SETTLED_TRAVEL_RATIO of topOut
// AND velocity is below
// AIRTIME_QUIESCENT_VELOCITY. A single average or a tail sample is not enough: both ends
// of the bike are typically still busy right at a stroke's edges (the far end still
// unloading as the near end tops out, or -- on a rear-wheel-first landing -- touching
// back down while the near end is still airborne), so only an interior stretch is
// unambiguously "in the air". Velocity is required alongside travel because travel alone
// can't tell a genuine hover from a manual: a rider can hold a wheel right at top-out
// while still driving the bike, which travel would read as at-rest but velocity would
// not.
func restsAtTopOut(travel, velocity []float64, s *stroke, topOut, maxTravel float64) bool {
	required := int(float64(s.End-s.Start+1) * AIRTIME_SETTLE_FRACTION)
	if required < 1 {
		required = 1
	}

	run := 0
	for i := s.Start; i <= s.End; i++ {
		if isSettledSample(travel[i], velocity[i], topOut, maxTravel) {
			run++
			if run >= required {
				return true
			}
		} else {
			run = 0
		}
	}
	return false
}

func (this *Processed) airtimes() {
	this.Airtimes = make([]*airtime, 0)

	var frontTopOut, rearTopOut float64
	if this.Front.Present {
		frontTopOut = this.Front.Strokes.topOut
	}
	if this.Rear.Present {
		rearTopOut = this.Rear.Strokes.topOut
	}

	if this.Front.Present && this.Rear.Present {
		// Pass 1: pair up front and rear air candidates that overlap in time. This is
		// the strongest signal (both ends agree independently) and consumes both
		// sides' candidates so they aren't also matched a second time below.
		for _, f := range this.Front.Strokes.airCandidates {
			if !f.airCandidate {
				continue
			}
			for _, r := range this.Rear.Strokes.airCandidates {
				if !r.airCandidate || !f.overlaps(r) {
					continue
				}
				f.airCandidate = false
				r.airCandidate = false

				// Min for both Start and End (not just Start) is deliberate: it
				// keeps the reported airtime inside the shorter of the two
				// overlapping candidates on both edges, matching Sufni.Bridge.
				at := &airtime{
					Start: float64(min(f.Start, r.Start)) / float64(this.SampleRate),
					End:   float64(min(f.End, r.End)) / float64(this.SampleRate),
				}
				this.Airtimes = append(this.Airtimes, at)
				break
			}
		}

		bothEndsAtRest := func(s *stroke) bool {
			return restsAtTopOut(this.Front.Travel, this.Front.Velocity, s, frontTopOut, this.Linkage.MaxFrontTravel) &&
				restsAtTopOut(this.Rear.Travel, this.Rear.Velocity, s, rearTopOut, this.Linkage.MaxRearTravel)
		}

		// Pass 2 & 3: single-sided fallback for candidates that didn't find a
		// same-time partner on the other end (e.g. one side's stroke got split
		// differently, or briefly dipped below AIRTIME_VELOCITY_THRESHOLD). Both
		// ends still have to independently look settled -- checked against the
		// OTHER side's own travel/velocity, never averaged with this stroke's side,
		// since averaging is exactly what lets a topped-out fork mask a loaded
		// shock (the manual false positive).
		for _, f := range this.Front.Strokes.airCandidates {
			if !f.airCandidate || coveredByAirtime(this.Airtimes, f, this.SampleRate) {
				continue
			}
			if !bothEndsAtRest(f) {
				continue
			}
			at := &airtime{
				Start: float64(f.Start) / float64(this.SampleRate),
				End:   float64(f.End) / float64(this.SampleRate),
			}
			this.Airtimes = append(this.Airtimes, at)
		}

		for _, r := range this.Rear.Strokes.airCandidates {
			if !r.airCandidate || coveredByAirtime(this.Airtimes, r, this.SampleRate) {
				continue
			}
			if !bothEndsAtRest(r) {
				continue
			}
			at := &airtime{
				Start: float64(r.Start) / float64(this.SampleRate),
				End:   float64(r.End) / float64(this.SampleRate),
			}
			this.Airtimes = append(this.Airtimes, at)
		}
	} else if this.Front.Present {
		for _, f := range this.Front.Strokes.airCandidates {
			if !f.airCandidate {
				continue
			}
			if !restsAtTopOut(this.Front.Travel, this.Front.Velocity, f, frontTopOut, this.Linkage.MaxFrontTravel) {
				continue
			}
			at := &airtime{
				Start: float64(f.Start) / float64(this.SampleRate),
				End:   float64(f.End) / float64(this.SampleRate),
			}
			this.Airtimes = append(this.Airtimes, at)
		}
	} else if this.Rear.Present {
		for _, r := range this.Rear.Strokes.airCandidates {
			if !r.airCandidate {
				continue
			}
			if !restsAtTopOut(this.Rear.Travel, this.Rear.Velocity, r, rearTopOut, this.Linkage.MaxRearTravel) {
				continue
			}
			at := &airtime{
				Start: float64(r.Start) / float64(this.SampleRate),
				End:   float64(r.End) / float64(this.SampleRate),
			}
			this.Airtimes = append(this.Airtimes, at)
		}
	}
}
