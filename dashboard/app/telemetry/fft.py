import numpy as np
from scipy.signal import welch # Für die Welch-Methode hinzugefügt
from scipy.fft import rfft, rfftfreq

from bokeh.models import CustomJS, ColumnDataSource # type: ignore
from bokeh.models.formatters import CustomJSTickFormatter # type: ignore
from bokeh.models.ranges import Range1d # type: ignore
from bokeh.models.tickers import FixedTicker # type: ignore
from bokeh.models.tools import HoverTool, WheelZoomTool # type: ignore
from bokeh.plotting import figure # type: ignore


TARGET_RESOLUTION = 0.025  # Hz - Feste Ziel-Frequenzauflösung


def _fft_data(travel: list[float], tick: float) -> dict[str, list]:
    if not travel or tick <= 0:  # Leere Eingabeliste oder ungültiger Tick behandeln
        # print("DEBUG: FFT _fft_data early exit: no travel or invalid tick.")
        return {"freqs": [], "spectrum": []}

    fs = 1.0 / tick  # Abtastrate

    N_min_for_fft = int(np.ceil(fs / TARGET_RESOLUTION))

    if N_min_for_fft <= 0:
        # print(f"DEBUG: FFT _fft_data early exit: N_min_for_fft <= 0. fs={fs}, TARGET_RESOLUTION={TARGET_RESOLUTION}")
        return {"freqs": [], "spectrum": []}

    original_num_points = len(travel)
    balanced_travel = np.array(travel, dtype=float) - np.mean(travel)


    if original_num_points < N_min_for_fft:
        n_fft = N_min_for_fft
        fft_output = rfft(balanced_travel, n=n_fft)
        spectrum = np.square(np.abs(fft_output))
        # Frequenzen müssen auch für diesen Fall generiert werden
        freqs = rfftfreq(n_fft, d=tick)
    else:
        nperseg_welch = N_min_for_fft
        nfft_welch = N_min_for_fft
        noverlap_welch = nperseg_welch // 2

        freqs, spectrum = welch(
            balanced_travel,
            fs=fs,
            window='hann',
            nperseg=nperseg_welch,
            noverlap=noverlap_welch,
            nfft=nfft_welch,
            scaling='spectrum',
            average='mean'
        )

    cutoff_freq = 10.0
    # Epsilon für Fließkommavergleiche ist gut, aber oft sind Indizes sicherer
    if freqs.size > 0: # Sicherstellen, dass freqs nicht leer ist
        valid_indices = np.where(freqs <= cutoff_freq + 1e-9)[0]
    else:
        valid_indices = np.array([], dtype=int)

    if len(valid_indices) > 0:
        freqs_filtered = freqs[valid_indices].tolist()
        
        spectrum_at_valid_indices = spectrum[valid_indices]
        # WICHTIG: NaNs und Infs aus dem Spektrum entfernen/ersetzen
        spectrum_cleaned = np.nan_to_num(spectrum_at_valid_indices, nan=0.0, posinf=np.finfo(np.float32).max, neginf=0.0)
        spectrum_filtered = spectrum_cleaned.tolist()
        
    else:
        freqs_filtered = []
        spectrum_filtered = []
        
    return {"freqs": freqs_filtered, "spectrum": spectrum_filtered}


def fft_figure(travel: list[float], tick: float, color: tuple[str],
               title: str) -> figure:
    data = _fft_data(travel, tick)
    source = ColumnDataSource(name='ds_fft', data=data)

    p = figure(
        title=title,
        min_height=150,
        min_border_left=70,
        min_border_right=50,
        sizing_mode='stretch_both',
        toolbar_location='above',
        tools='xpan,reset',
        active_drag='xpan',
        x_axis_label="Frequency (Hz)",
        y_axis_label="Power",
        output_backend='webgl')

    p.y_range.start = 0

    wzt = WheelZoomTool(maintain_focus=False, dimensions='width')
    p.add_tools(wzt)

    ht = HoverTool(name='ht', tooltips=[
        ("Frequency", "@freqs{0.000} Hz"),
        ("Power", "@spectrum{0.00e}")
    ], mode='vline', attachment='above')
    p.add_tools(ht)

    current_spectrum = np.array(data['spectrum'])
    if current_spectrum.size > 0:
        ticker_max = np.max(current_spectrum)
        if not np.isfinite(ticker_max):
            ticker_max = 1.0 
    else:
        ticker_max = 1.0

    if ticker_max <= 0:
        p.yaxis.ticker = FixedTicker(ticks=[0, 0.5, 1.0])
        p.y_range.end = 1.0
    else:
        p.yaxis.ticker = FixedTicker(ticks=[
            0,
            ticker_max / 2.0,
            ticker_max,
        ])
        p.y_range.end = ticker_max * 1.05

    p.yaxis.formatter = CustomJSTickFormatter(
        args={}, code='''
            const tick_value = tick;
            if (tick_value < 0) return "";
            if (tick_value === 0) return "-∞ dB";
            if (!isFinite(tick_value)) {
                return (tick_value > 0 ? "+∞" : "-∞") + " dB";
            }
            const dBValue = 10 * Math.log10(tick_value);
            if (!isFinite(dBValue)) {
                 return "-∞ dB";
            }
            return dBValue.toFixed(1) + " dB";
        ''')

    p.x_range = Range1d(0.0, 10.0, bounds=(0.0, 10.0))

    if len(source.data['freqs']) > 0:
        bar_width_val = max(TARGET_RESOLUTION * 0.75, 0.001) 
    else:
        bar_width_val = 0.1 


    p.vbar(name='b_fft', x='freqs', bottom=0, top='spectrum',
           source=source, width=bar_width_val, line_width=1,
           color=color, fill_alpha=0.6)

    # Korrigierter f-String für CustomJS code
    # Alle { und } die zu JavaScript gehören, werden als {{ und }} maskiert.
    # Die Python-Variable {TARGET_RESOLUTION} wird korrekt eingesetzt.
    custom_js_code = f'''
        const new_data = cb_obj.data;
        const spectrum = new_data.spectrum;
        const local_yr = yr;
        const local_ticker = ticker;
        const vbar = vbar_glyph;

        // console.log("FFT JS: spectrum received:", spectrum); 

        local_yr.start = 0;
        let Smax = 0;
        if (spectrum && spectrum.length > 0) {{ // JS-Block, daher {{
            try {{ // JS-Block, daher {{
                Smax = Math.max(...spectrum);
            }} catch (e) {{ // JS-Block, daher {{
                console.error("FFT JS: Error in Math.max(...spectrum):", e);
                Smax = NaN; // Fehlerfall explizit machen
            }}
        }} else {{ // JS-Block, daher {{
            Smax = 0; 
        }}
        // console.log("FFT JS: Smax calculated:", Smax);

        if (!isFinite(Smax) || Smax <= 0) {{ // JS-Block, daher {{
            // console.warn("FFT JS: Smax is not finite or <= 0. Smax:", Smax, ". Setting Y-range to fallback.");
            local_ticker.ticks = [0, 0.5, 1.0];
            local_yr.end = 1.0;
        }} else {{ // JS-Block, daher {{
            local_ticker.ticks = [0, Smax / 2.0, Smax];
            local_yr.end = Smax * 1.05;
        }}
        // console.log("FFT JS: yr.end set to:", local_yr.end, "yr.start:", local_yr.start);


        const target_resolution_js = {TARGET_RESOLUTION}; // Python-Variable wird hier eingesetzt
        
        if (new_data.freqs && new_data.freqs.length > 0) {{ // JS-Block, daher {{
            vbar.glyph.width = Math.max(target_resolution_js * 0.75, 0.001);
        }} else {{ // JS-Block, daher {{
            vbar.glyph.width = 0.1; 
        }}
    '''

    source.js_on_change('data', CustomJS(args=dict(
        yr=p.y_range, ticker=p.yaxis.ticker, vbar_glyph=p.select_one({'name': 'b_fft'})
    ), code=custom_js_code))
    return p


def update_fft(travel: list[float], tick: float) -> dict:
    """Aktualisiert die FFT-Daten für einen Plot."""
    data = _fft_data(travel, tick)
    return data