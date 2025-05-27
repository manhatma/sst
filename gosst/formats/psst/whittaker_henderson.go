package psst

import (
	"errors"
	"fmt"
	"math"
)

// WH_MAX_ORDER ist die maximal unterstützte Ordnung für den WH-Filter, basierend auf DIFF_COEFF_WH.
const WH_MAX_ORDER = 5

// WH_DIFF_COEFF sind die Koeffizienten für die numerische Differentiation,
// die zur Erstellung der D-Matrix im WH-Filter verwendet werden.
// Index ist Ordnung-1.
var WH_DIFF_COEFF = [][]float64{
	{-1, 1},                // Ordnung 1
	{1, -2, 1},             // Ordnung 2
	{-1, 3, -3, 1},         // Ordnung 3
	{1, -4, 6, -4, 1},      // Ordnung 4
	{-1, 5, -10, 10, -5, 1}, // Ordnung 5
}

// WhittakerHendersonSmoother speichert die vorberechnete Matrix für das Smoothing.
type WhittakerHendersonSmoother struct {
	matrix [][]float64 // Die Cholesky-zerlegte Dreiecksmatrix (L)
	length int         // Erwartete Länge der zu glättenden Daten
}

// makeDprimeDWH erstellt eine symmetrische Banddiagonalmatrix D'*D aus der Differenzmatrix D der p-ten Ordnung.
// 'order' ist die Strafordnung 'p', 'size' ist die Anzahl der Datenpunkte.
func makeDprimeDWH(order, size int) ([][]float64, error) {
	if order < 1 || order > WH_MAX_ORDER {
		return nil, fmt.Errorf("WhittakerSmoother: Ungültige Ordnung %d, muss zwischen 1 und %d liegen", order, WH_MAX_ORDER)
	}
	if size <= order {
		return nil, fmt.Errorf("WhittakerSmoother: Größe (%d) muss größer als die Ordnung (%d) sein", size, order)
	}

	coeffs := WH_DIFF_COEFF[order-1]
	dPrimeD := make([][]float64, order+1)
	for d := 0; d <= order; d++ {
		dPrimeD[d] = make([]float64, size-d)
	}

	for d := 0; d <= order; d++ {
		bandToFill := dPrimeD[d]
		currentBandLength := len(bandToFill)

		for i := 0; i < (currentBandLength+1)/2; i++ {
			sum := 0.0
			jLowerBound := 0
			if tempJLower := i - currentBandLength + len(coeffs) - d; tempJLower > 0 {
				jLowerBound = tempJLower
			}
			jUpperBound1 := i + 1
			jUpperBound2 := len(coeffs) - d
			jFinalUpperBound := jUpperBound1
			if jUpperBound2 < jUpperBound1 {
				jFinalUpperBound = jUpperBound2
			}

			for j := jLowerBound; j < jFinalUpperBound; j++ {
				sum += coeffs[j] * coeffs[j+d]
			}
			bandToFill[i] = sum
			if i != currentBandLength-1-i {
				bandToFill[currentBandLength-1-i] = sum
			}
		}
	}
	return dPrimeD, nil
}

// timesLambdaPlusIdentWH modifiziert b zu I + lambda*b (wobei I die Identitätsmatrix ist).
// b ist die D'*D Matrix.
func timesLambdaPlusIdentWH(b [][]float64, lambda float64) {
	if len(b) == 0 {
		return
	}
	for i := 0; i < len(b[0]); i++ {
		b[0][i] = 1.0 + b[0][i]*lambda
	}
	for d := 1; d < len(b); d++ {
		for i := 0; i < len(b[d]); i++ {
			b[d][i] = b[d][i] * lambda
		}
	}
}

// choleskyLWH führt die Cholesky-Zerlegung L*L' für eine symmetrische positiv-definite Banddiagonalmatrix durch.
// Die Eingabe b (welche I + lambda*D'D ist) wird durch die untere Dreiecksmatrix L ersetzt.
func choleskyLWH(b [][]float64) error {
	if len(b) == 0 {
		return errors.New("Cholesky: Matrix ist leer")
	}
	n := len(b[0])
	dmax := len(b) - 1

	for i := 0; i < n; i++ {
		for jCol := math.Max(0, float64(i-dmax)); int(jCol) <= i; jCol++ {
			j_java := int(jCol)
			sum := 0.0
			k_lower_bound := 0
			if temp_k_lower := i - dmax; temp_k_lower > k_lower_bound {
				k_lower_bound = temp_k_lower
			}
			if temp_k_lower := j_java - dmax; temp_k_lower > k_lower_bound {
				k_lower_bound = temp_k_lower
			}

			for k := k_lower_bound; k < j_java; k++ {
				dAik := i - k
				dAjk := j_java - k
				if dAik >= 0 && dAik < len(b) && k < len(b[dAik]) &&
					dAjk >= 0 && dAjk < len(b) && k < len(b[dAjk]) {
					sum += b[dAik][k] * b[dAjk][k]
				} else {
					return fmt.Errorf("Cholesky: Index außerhalb des Bereichs während der Summe bei i=%d, j=%d, k=%d", i, j_java, k)
				}
			}

			if i == j_java {
				diagVal := b[0][i] - sum
				if diagVal <= 1e-12 {
					return fmt.Errorf("Cholesky: Matrix nicht positiv definit bei i=%d, val=%f. Lambda prüfen oder Datenqualität", i, diagVal)
				}
				b[0][i] = math.Sqrt(diagVal)
			} else {
				bandIndex_Lij := i - j_java
				if b[0][j_java] == 0 {
					return fmt.Errorf("Cholesky: Division durch Null aufgrund von L_jj=0 bei j=%d", j_java)
				}
				b[bandIndex_Lij][j_java] = (b[bandIndex_Lij][j_java] - sum) / b[0][j_java]
			}
		}
	}
	return nil
}

// solveWH löst L*y = vec (Vorwärtssubstitution) und dann L'*x = y (Rückwärtssubstitution).
// b ist die Cholesky-zerlegte Matrix L. vec sind die Eingabedaten.
// Gibt x zurück, die geglätteten Daten.
func solveWH(b [][]float64, vec []float64) ([]float64, error) {
	if len(b) == 0 {
		return nil, errors.New("Solve: Cholesky-Matrix L ist leer")
	}
	if len(b[0]) != len(vec) {
		return nil, fmt.Errorf("Solve: Spalten der Matrix L (%d) stimmen nicht mit der Länge des Datenvektors (%d) überein", len(b[0]), len(vec))
	}

	n := len(vec)
	out := make([]float64, n)
	dmax := len(b) - 1

	for i := 0; i < n; i++ {
		sum := 0.0
		j_lower_bound := 0
		if temp_j_lower := i - dmax; temp_j_lower > 0 {
			j_lower_bound = temp_j_lower
		}
		for j := j_lower_bound; j < i; j++ {
			bandIndex_Lij := i - j
			if bandIndex_Lij >= 0 && bandIndex_Lij < len(b) && j < len(b[bandIndex_Lij]) {
				sum += b[bandIndex_Lij][j] * out[j]
			} else {
				return nil, fmt.Errorf("Solve (vorwärts): Index außerhalb des Bereichs für L_ij bei i=%d, j=%d", i, j)
			}
		}
		if b[0][i] == 0 {
			return nil, fmt.Errorf("Solve (vorwärts): Division durch Null aufgrund von L_ii=0 bei i=%d", i)
		}
		out[i] = (vec[i] - sum) / b[0][i]
	}

	for i := n - 1; i >= 0; i-- {
		sum := 0.0
		j_upper_bound := n
		if temp_j_upper := i + dmax + 1; temp_j_upper < n {
			j_upper_bound = temp_j_upper
		}
		for j := i + 1; j < j_upper_bound; j++ {
			bandIndex_Lji := j - i
			if bandIndex_Lji >= 0 && bandIndex_Lji < len(b) && i < len(b[bandIndex_Lji]) {
				sum += b[bandIndex_Lji][i] * out[j]
			} else {
				return nil, fmt.Errorf("Solve (rückwärts): Index außerhalb des Bereichs für L_ji bei i=%d, j=%d", i, j)
			}
		}
		if b[0][i] == 0 {
			return nil, fmt.Errorf("Solve (rückwärts): Division durch Null aufgrund von L_ii=0 bei i=%d", i)
		}
		out[i] = (out[i] - sum) / b[0][i]
	}
	return out, nil
}

// NewWhittakerHendersonSmoother erstellt eine Smoother-Instanz.
// length: Anzahl der zu glättenden Datenpunkte.
// order: Strafordnung p für den WH-Smoother.
// lambda: Glättungsparameter.
func NewWhittakerHendersonSmoother(length, order int, lambda float64) (*WhittakerHendersonSmoother, error) {
	if length <= order || length < 2 {
		return nil, fmt.Errorf("Datenlänge %d zu kurz für Ordnung %d oder minimale Verarbeitung", length, order)
	}
	matrixA, err := makeDprimeDWH(order, length)
	if err != nil {
		return nil, fmt.Errorf("Fehler beim Erstellen der D'D-Matrix: %w", err)
	}
	timesLambdaPlusIdentWH(matrixA, lambda)
	err = choleskyLWH(matrixA)
	if err != nil {
		return nil, fmt.Errorf("Cholesky-Zerlegung fehlgeschlagen: %w", err)
	}
	return &WhittakerHendersonSmoother{matrix: matrixA, length: length}, nil
}

// Smooth wendet die Whittaker-Henderson-Glättung auf die Daten an.
func (whs *WhittakerHendersonSmoother) Smooth(data []float64) ([]float64, error) {
	if len(data) != whs.length {
		return nil, fmt.Errorf("Datenlänge %d stimmt nicht mit der vorkonfigurierten Länge des Smoothers %d überein", len(data), whs.length)
	}
	if whs.matrix == nil {
		return nil, errors.New("Smoother-Matrix nicht initialisiert")
	}
	return solveWH(whs.matrix, data)
}