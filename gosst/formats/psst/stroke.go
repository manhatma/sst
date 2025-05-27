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
		// Anpassung der Logik basierend auf der ursprünglichen Implementierung:
		// sort.SearchFloat64s gibt den Index 'i' zurück, an dem v eingefügt werden würde.
		// Wenn v größer oder gleich dem letzten Bin-Wert ist ODER v nicht exakt einem Bin-Wert entspricht,
		// wird der vorherige Bin-Index verwendet.
		if i == len(bins) || (i > 0 && v < bins[i]) { // Wenn v kleiner als bins[i] ist, gehört es zum vorherigen Bin.
			i -= 1
		}
		if i < 0 { // Sicherstellen, dass der Index nicht negativ wird.
			i = 0
		} else if i >= len(bins)-1 && len(bins) > 1 { // Wenn der Index auf dem letzten Bin oder darüber liegt (und es mehr als ein Bin gibt)
			i = len(bins) - 2 // Daten werden dem vorletzten Bin zugeordnet (da Bins die Kanten darstellen)
		} else if len(bins) == 1 { // Nur ein Bin-Rand -> alle Daten gehören zum Index 0.
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

	// Stellen Sie sicher, dass mn und mx sinnvoll sind, auch wenn alle Werte gleich sind
	mn := (math.Floor(minVal/step) - 0.5) * step
	mx := (math.Floor(maxVal/step) + 1.5) * step
	if mx <= mn { // Fallback, falls mx nicht größer als mn ist (z.B. wenn alle v-Werte gleich sind)
		mx = mn + step
	}

	numBins := int((mx-mn)/step) + 1
	if numBins <= 0 { // Mindestens ein Bin
		numBins = 1
	}

	bins = linspace(mn, mx, numBins)
	if len(bins) == 0 { // Sollte nicht passieren, wenn numBins > 0
		return []float64{mn}, digitize(v, []float64{mn})
	}
	data = digitize(v, bins)
	return bins, data
}

func (this *stroke) overlaps(other *stroke) bool {
	l := max(this.End-this.Start, other.End-other.Start)
	if l == 0 { // Vermeide Division durch Null, wenn beide Längen 0 sind
		return false
	}
	s := max(this.Start, other.Start)
	e := min(this.End, other.End)
	overlapDuration := e - s
	if overlapDuration < 0 { // Kein Überlapp
		overlapDuration = 0
	}
	return float32(overlapDuration) >= AIRTIME_OVERLAP_THRESHOLD*float32(l)
}

// getPercentileValue ermittelt den Wert eines bestimmten Perzentils aus einem Slice von float64-Werten.
// Es erstellt eine Kopie des Eingabe-Slices, sortiert diese und wählt dann das Element aus,
// das dem angegebenen Perzentil entspricht (z. B. 0.95 für das 95. Perzentil).
// Diese Implementierung verwendet die "Nearest Rank"-Methode, bei der zur Bestimmung des Index aufgerundet wird.
// Wenn der Eingabe-Slice leer ist, wird 0.0 zurückgegeben.
func getPercentileValue(values []float64, percentile float64) float64 {
	n := len(values)
	if n == 0 {
		return 0.0 // Oder Fehlerbehandlung nach Bedarf
	}

	// Eine Kopie erstellen, um den ursprünglichen Slice nicht zu verändern
	sortedValues := append([]float64(nil), values...)
	sort.Float64s(sortedValues)

	if percentile <= 0.0 {
		return sortedValues[0]
	}
	if percentile >= 1.0 {
		return sortedValues[n-1]
	}

	// Den 0-basierten Index mit der "Nearest Rank"-Methode berechnen (Aufrunden von P*N)
	// k = ceil(P * N) -> 1-basierter Rang
	// index = k - 1   -> 0-basierter Index
	index := int(math.Ceil(percentile*float64(n))) - 1

	// Index auf gültige Grenzen [0, n-1] beschränken.
	if index < 0 {
		index = 0
	}
	if index >= n {
		index = n - 1
	}

	return sortedValues[index]
}

func newStroke(start, end int, duration float64, travel, velocity []float64, maxTravel float64) *stroke {
	s := &stroke{
		Start:    start,
		End:      end,
		length:   travel[end] - travel[start],
		duration: duration,
	}

	velSubSlice := velocity[start : end+1] // Für Max/Min-Berechnung
	travelSubSlice := travel[start : end+1] // Für Sum/Max-Berechnung und P95

	var mv float64
	if len(velSubSlice) > 0 { // Sicherstellen, dass der Slice nicht leer ist
		if s.length < 0 { // Rebound
			mv = floats.Min(velSubSlice)
		} else { // Compression
			mv = floats.Max(velSubSlice)
		}
	}

	bo := 0
	// Korrigierte Bottomout-Zählung: Iteriere über den travelSubSlice
	// und stelle sicher, dass 'i' innerhalb der Grenzen von travel bleibt.
	// Der äußere Loop für 'i' sollte 'start' bis 'end' des Strokes abdecken.
	// Der innere Loop springt über aufeinanderfolgende Bottomout-Samples.
	for i := start; i <= end; { // Index 'i' bezieht sich auf den originalen 'travel' Slice
		if travel[i] > maxTravel-BOTTOMOUT_THRESHOLD {
			bo++
			// Überspringe alle aufeinanderfolgenden Samples, die ebenfalls Bottomouts sind
			for ; i <= end && travel[i] > maxTravel-BOTTOMOUT_THRESHOLD; i++ {
			}
		} else {
			i++
		}
	}


	// 95%-Perzentil für Travel
	p95t := getPercentileValue(travelSubSlice, 0.95)

	// 95%-Perzentile für Velocity: getrennt nach Compression (+) und Rebound (–)
	// Compression (>0)
	var compVelocities []float64
	for _, v := range velSubSlice {
		if v > 0 {
			compVelocities = append(compVelocities, v)
		}
	}
	p95Comp := getPercentileValue(compVelocities, 0.95)

	// Rebound (<0) – wir betrachten die Magnitude
	var rebMagnitudes []float64
	for _, v := range velSubSlice {
		if v < 0 {
			rebMagnitudes = append(rebMagnitudes, -v) // Magnitude
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
	this.idlings = make([]*stroke, 0) // Idlings auch initialisieren

	for i, currentStroke := range strokes {
		if math.Abs(currentStroke.length) < STROKE_LENGTH_THRESHOLD &&
			currentStroke.duration >= IDLING_DURATION_THRESHOLD {

			// Airtime-Kandidatenprüfung (ursprüngliche Logik beibehalten)
			if i > 0 && i < len(strokes)-1 &&
				currentStroke.Stat.MaxTravel <= STROKE_LENGTH_THRESHOLD && // Idling ist nah am Nullpunkt
				currentStroke.duration >= AIRTIME_DURATION_THRESHOLD &&
				strokes[i+1].Stat.MaxVelocity >= AIRTIME_VELOCITY_THRESHOLD { // Nächster Stroke beginnt mit hoher Geschwindigkeit
				currentStroke.airCandidate = true
			}
			this.idlings = append(this.idlings, currentStroke)
		} else if currentStroke.length >= STROKE_LENGTH_THRESHOLD {
			this.Compressions = append(this.Compressions, currentStroke)
		} else if currentStroke.length <= -STROKE_LENGTH_THRESHOLD {
			this.Rebounds = append(this.Rebounds, currentStroke)
		}
		// Optional: Was passiert mit Strokes, die keine der Bedingungen erfüllen?
		// Sie könnten z.B. auch als Idlings oder eine separate Kategorie behandelt werden.
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
	if len(velocity) == 0 || float64(rate) == 0 { // Vorzeitiger Ausstieg bei ungültigen Eingaben
		return []*stroke{}
	}

	var startIndex int
	var startSign int8

	for i := 0; i < len(velocity); { // Äußere Schleife, 'i' wird manuell inkrementiert
		startIndex = i
		startSign = sign(velocity[i])

		// Innere Schleife, um das Ende des aktuellen Segments mit gleichem Vorzeichen zu finden
		segmentEndIndex := i
		for ; segmentEndIndex < len(velocity)-1 && sign(velocity[segmentEndIndex+1]) == startSign; segmentEndIndex++ {
		}

		// Dauer des Segments berechnen
		// Anzahl der Samples im Segment: segmentEndIndex - startIndex + 1
		d := float64(segmentEndIndex-startIndex+1) / float64(rate)

		// Potenzielles Zusammenführen von kleinen "Idling"-Strokes
		// Überprüfen, ob das aktuelle Segment kurz ist und der vorherige Stroke ebenfalls kurz war.
		currentSegmentMaxTravel := 0.0
		if startIndex <= segmentEndIndex && segmentEndIndex < len(travel) {
			subTravel := travel[startIndex : segmentEndIndex+1]
			if len(subTravel) > 0 {
				currentSegmentMaxTravel = floats.Max(subTravel)
			}
		}


		if currentSegmentMaxTravel < STROKE_LENGTH_THRESHOLD &&
			len(strokes) > 0 &&
			strokes[len(strokes)-1].Stat.MaxTravel < STROKE_LENGTH_THRESHOLD &&
			sign(velocity[startIndex]) == sign(velocity[strokes[len(strokes)-1].Start]) { // Nur zusammenführen, wenn das Vorzeichen gleich bleibt (oder beide 0 sind)

			// Letzten Stroke erweitern
			strokes[len(strokes)-1].End = segmentEndIndex
			strokes[len(strokes)-1].duration += d
			// Neuberechnung der Statistiken für den zusammengeführten Stroke wäre hier ideal,
			// aber die ursprüngliche Logik hat dies nicht explizit getan.
			// Für eine genauere Zusammenführung müssten die Statistiken aktualisiert werden.
			// Hier wird nur Dauer und Ende aktualisiert.
            // Aktualisiere auch die Länge, wenn es ein Idling ist (Länge nahe Null)
            if strokes[len(strokes)-1].length < STROKE_LENGTH_THRESHOLD && strokes[len(strokes)-1].length > -STROKE_LENGTH_THRESHOLD {
                 strokes[len(strokes)-1].length = travel[segmentEndIndex] - travel[strokes[len(strokes)-1].Start]
            }


		} else {
			// Neuen Stroke erstellen
			s := newStroke(startIndex, segmentEndIndex, d, travel, velocity, maxTravel)
			strokes = append(strokes, s)
		}

		i = segmentEndIndex + 1 // 'i' für die nächste Iteration der äußeren Schleife setzen
	}
	return strokes
}