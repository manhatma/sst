import numpy as np
from bokeh.models import CustomJS
from bokeh.models.formatters import CustomJSTickFormatter
from bokeh.models.ranges import Range1d
from bokeh.models.sources import ColumnDataSource
from bokeh.models.tickers import FixedTicker
from bokeh.models.tools import HoverTool, WheelZoomTool
from bokeh.plotting import figure
from scipy.fft import rfft, rfftfreq

def _fft_data(travel: list[float], tick: float) -> dict[str, np.array]:
    balanced_travel = travel - np.mean(travel)
    n = np.max([20000, len(balanced_travel)])
    balanced_travel_f = rfft(balanced_travel, n=n)
    balanced_spectrum = np.square(np.abs(balanced_travel_f)).tolist()
    freqs = rfftfreq(n, tick)
    freqs = freqs[freqs <= 10].tolist()  # cut off FFT graph at 10 Hz
    return dict(freqs=freqs, spectrum=balanced_spectrum[:len(freqs)])

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
    wzt = WheelZoomTool(maintain_focus=False, dimensions='width')
    p.add_tools(wzt)
    ht = HoverTool(name='ht', tooltips="@freqs Hz",
                   mode='vline', attachment='above')
    p.add_tools(ht)
    temp_spectrum = np.array(data['spectrum'])
    ticker_max = np.max(data['spectrum'])
    p.yaxis.ticker = FixedTicker(ticks=[
        0,
        ticker_max / 2.0,
        ticker_max,
    ])
    p.yaxis.formatter = CustomJSTickFormatter(
        args={}, code='''
            if (tick <= 0) {
                return "0";
            }
            const t = Math.floor(20 * Math.log10(tick));
            return isNaN(t) ? "" : t;
        ''')
    p.x_range = Range1d(
        0.0,
        800.0 / len(source.data['freqs']) * 3.0,
        bounds=(0.0, 10.0))
    p.y_range = Range1d(
        0.0,
        ticker_max)
    bar_width = 4.9 / len(source.data['freqs'])
    p.vbar(name='b_fft', x='freqs', bottom=0, top='spectrum',
           source=source, width=bar_width, line_width=2,
           color=color, fill_alpha=0.4)
    source.js_on_change('data', CustomJS(args=dict(
        xr=p.x_range, yr=p.y_range, ticker=p.yaxis.ticker), code='''
            xr.end = 800 / cb_obj.data.freqs.length * 3;
            yr.start = 0;
            yr.end = Math.max(...cb_obj.data.spectrum);
            const tickerMin = 0;
            const tickerMax = Math.max(...cb_obj.data.spectrum);
            ticker.ticks = [tickerMin, (tickerMin + tickerMax) / 2.0, tickerMax];
        '''))
    return p

def fft_comparison_figure(front_travel: list[float], rear_travel: list[float],
                          tick: float, front_color: tuple[str],
                          rear_color: tuple[str]) -> figure:
    front_data = _fft_data(front_travel, tick)
    rear_data = _fft_data(rear_travel, tick)
    front_source = ColumnDataSource(name='ds_fft_front_comp', data=front_data)
    rear_source = ColumnDataSource(name='ds_fft_rear_comp', data=rear_data)

    all_max = max(max(front_data['spectrum']), max(rear_data['spectrum']))
    p = figure(
        title="Frequency comparison",
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
    wzt = WheelZoomTool(maintain_focus=False, dimensions='width')
    p.add_tools(wzt)
    p.yaxis.ticker = FixedTicker(ticks=[0, all_max / 2.0, all_max])
    p.yaxis.formatter = CustomJSTickFormatter(
        args={}, code='''
            if (tick <= 0) {
                return "0";
            }
            const t = Math.floor(20 * Math.log10(tick));
            return isNaN(t) ? "" : t;
        ''')
    p.x_range = Range1d(
        0.0,
        800.0 / len(front_source.data['freqs']) * 3.0,
        bounds=(0.0, 10.0))
    p.y_range = Range1d(0.0, all_max)
    p.line(x='freqs', y='spectrum', source=front_source,
            line_dash='solid', line_width=2, color=front_color,
           legend_label='Front')
    p.line(x='freqs', y='spectrum', source=rear_source,
            line_dash='solid', line_width=2, color=rear_color,
           legend_label='Rear')
    update_code = '''
        const f_spec = front_src.data.spectrum;
        const r_spec = rear_src.data.spectrum;
        xr.end = 800 / front_src.data.freqs.length * 3;
        yr.start = 0;
        const tickerMax = Math.max(Math.max(...f_spec), Math.max(...r_spec));
        yr.end = tickerMax;
        ticker.ticks = [0, tickerMax / 2.0, tickerMax];
    '''
    cb = CustomJS(
        args=dict(front_src=front_source, rear_src=rear_source,
                  xr=p.x_range, yr=p.y_range, ticker=p.yaxis.ticker),
        code=update_code)
    front_source.js_on_change('data', cb)
    rear_source.js_on_change('data', cb)
    return p

def update_fft(travel: list[float], tick: float):
    data = _fft_data(travel, tick)
    return dict(data=data)