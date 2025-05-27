package psst

import (
	"errors"
	"fmt"
	"math"
)

// ModifiedSincSmoother holds the precomputed kernel for MS smoothing.
type ModifiedSincSmoother struct {
	kernel []float64
	mValue int // half-width 'm' of the kernel
	nValue int // degree 'n' of the MS kernel
}

// sinc calculates the sinc function sin(pi*x)/(pi*x).
func sinc(x float64) float64 {
	if x == 0.0 {
		return 1.0
	}
	piX := math.Pi * x
	return math.Sin(piX) / piX
}

// NewModifiedSincSmoother creates a new smoother instance for MS smoothing.
// n_ms: degree parameter for MS kernel (e.g., 2, 4, 6, 8 from the paper [cite: 83, 97]).
// m_ms: half-width of the MS kernel. Controls smoothness; larger m = more smoothing.
//       Minimum m_ms is typically n_ms/2 + 2[cite: 261].
// alpha_ms: Gaussian width parameter for the window function (e.g., 4.0 [cite: 88]).
func NewModifiedSincSmoother(n_ms, m_ms int, alpha_ms float64) (*ModifiedSincSmoother, error) {
	min_m_required := n_ms/2 + 2
	if m_ms < min_m_required {
		return nil, fmt.Errorf("MS Smoother: m_ms (%d) is too small for n_ms (%d). Must be >= %d", m_ms, n_ms, min_m_required)
	}

	kernelSize := 2*m_ms + 1
	kernel := make([]float64, kernelSize)

	// Calculate kernel values based on Equations 3, 4, 5 from Schmid et al., 2022 [cite: 82]
	// For n_ms <= 4, no correction terms (eq. 7) are needed[cite: 105].
	// The kernel is a(i) = A * w_alpha(x) * sinc_term(x)
	// x = i_kernel / (m_ms + 1), where i_kernel ranges from -m_ms to m_ms.

	var sumKernel float64
	for k_idx := 0; k_idx < kernelSize; k_idx++ {
		i_kernel := float64(k_idx - m_ms) // Converts array index to kernel index from -m to m
		x := i_kernel / (float64(m_ms) + 1.0)

		// Window function w_alpha(x) - Eq. 4 [cite: 82]
		w_alpha_x := math.Exp(-alpha_ms*x*x) +
			math.Exp(-alpha_ms*(x+2.0)*(x+2.0)) +
			math.Exp(-alpha_ms*(x-2.0)*(x-2.0)) -
			2.0*math.Exp(-alpha_ms) -
			math.Exp(-9.0*alpha_ms)

		// Sinc part: sin(((n_ms+4)/2)*pi*x) / (((n_ms+4)/2)*pi*x) - Eq. 3 [cite: 82]
		// Our sinc(val) is sin(pi*val)/(pi*val). So, val = ((n_ms+4)/2)*x
		sincArg := (float64(n_ms) + 4.0) / 2.0 * x
		sincVal := sinc(sincArg)

		// No correction terms for n_ms=2 [cite: 105]
		kernel[k_idx] = w_alpha_x * sincVal
		sumKernel += kernel[k_idx]
	}

	// Normalize kernel such that sum of coefficients is 1 - Eq. 6 [cite: 89]
	if sumKernel == 0 {
		// This should not happen with valid parameters
		return nil, errors.New("MS Smoother: kernel sum is zero, cannot normalize")
	}
	for k_idx := 0; k_idx < kernelSize; k_idx++ {
		kernel[k_idx] /= sumKernel
	}

	return &ModifiedSincSmoother{kernel: kernel, mValue: m_ms, nValue: n_ms}, nil
}

// Smooth applies MS smoothing (convolution) to the data.
// Produces an output of the same length as data, typically using zero-padding at boundaries implicitly.
func (ms *ModifiedSincSmoother) Smooth(data []float64) ([]float64, error) {
	if ms.kernel == nil {
		return nil, errors.New("MS Smoother: kernel not initialized")
	}
	if len(ms.kernel) == 0 {
		return nil, errors.New("MS Smoother: kernel is empty")
	}
	if len(data) == 0 {
		return []float64{}, nil
	}

	dataLen := len(data)
	kernelLen := len(ms.kernel)
	// m is the kernel half-width, ms.mValue should be (kernelLen - 1) / 2

	smoothedData := make([]float64, dataLen)

	for i := 0; i < dataLen; i++ {
		var sum float64
		for k := 0; k < kernelLen; k++ {
			// Kernel index k. Effective data index for convolution:
			dataIdx := i - (k - ms.mValue) // This is equivalent to i + ms.mValue - k

			if dataIdx >= 0 && dataIdx < dataLen {
				sum += data[dataIdx] * ms.kernel[k]
			}
			// Implicit zero-padding: if dataIdx is out of bounds, data[dataIdx]*kernel[k] is not added.
			// The paper mentions linear extrapolation for boundary handling which is more advanced. [cite: 181]
		}
		smoothedData[i] = sum
	}
	return smoothedData, nil
}