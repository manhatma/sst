var m = require("mithril")
var Session = require("./Session")
var Login = require("../views/Login")
var VideoPlayer = require("../views/VideoPlayer")
var Layout = require("../views/Layout")

var SST = {
  setError: function(error) {
    Layout.error = error
  },
  getCookie: function (name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  },
  init_models: function() {
    // Store travel graph Span in VideoPlayer
    VideoPlayer.travelSpan = Bokeh.documents[0].get_model_by_name("s_current_time")

    // Map
    SST.update.map(Session.current.full_track, Session.current.session_track)

    // Disable tools on mobile
    if( /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ) {
      const disable_tools = function(item) {
        if (item.toolbar) {
          if (item.toolbar.active_drag) { item.toolbar.active_drag = null; }
          if (item.active_scroll) { item.active_scroll = null; }
          if (item.active_inspect) { item.active_inspect = null; }
        }
      };
      Bokeh.documents[0].roots().forEach(item => {
        disable_tools(item);
        if (item.children) {
          item.children.forEach(child => disable_tools(child));
        }
      });
    }
  },
  seekVideo: VideoPlayer.seek,
  update: {
    process_double_json: function(u) {
      const f_fft = Bokeh.documents[0].get_model_by_name("front_fft");
      const r_fft = Bokeh.documents[0].get_model_by_name("rear_fft");
      const f_thist = Bokeh.documents[0].get_model_by_name("front_travel_hist");
      const r_thist = Bokeh.documents[0].get_model_by_name("rear_travel_hist");
      const f_vhist = Bokeh.documents[0].get_model_by_name("front_velocity_hist");
      const r_vhist = Bokeh.documents[0].get_model_by_name("rear_velocity_hist");
      const cbalance = Bokeh.documents[0].get_model_by_name("balance_compression");
      const rbalance = Bokeh.documents[0].get_model_by_name("balance_rebound");
      const thist_comp = Bokeh.documents[0].get_model_by_name("thist_comp");

      SST.update.fft(f_fft, u.front.fft);
      SST.update.fft(r_fft, u.rear.fft);
      SST.update.thist(f_thist, u.front.thist);
      SST.update.thist(r_thist, u.rear.thist);
      SST.update.vhist(f_vhist.children[0], f_vhist.children[1], u.front.vhist);
      SST.update.vhist(r_vhist.children[0], r_vhist.children[1], u.rear.vhist);
      SST.update.vbands(f_vhist.children[2], u.front.vbands);
      SST.update.vbands(r_vhist.children[2], u.rear.vbands);
      SST.update.balance(cbalance, u.balance.compression);
      SST.update.balance(rbalance, u.balance.rebound);
      if (thist_comp) {
        SST.update.thist_comp(thist_comp, u.front.thist, u.rear.thist);
      }
    },
    process_single_json: function(u) {
      const fft = Bokeh.documents[0].get_model_by_name("fft");
      const thist = Bokeh.documents[0].get_model_by_name("travel_hist");
      const vhist = Bokeh.documents[0].get_model_by_name("velocity_hist");

      if (u.front !== null) {
        SST.update.fft(fft, u.front.fft);
        SST.update.thist(thist, u.front.thist);
        SST.update.vhist(vhist.children[0], vhist.children[1], u.front.vhist);
        SST.update.vbands(vhist.children[2], u.front.vbands);
      } else {
        SST.update.fft(fft, u.rear.fft);
        SST.update.thist(thist, u.rear.thist);
        SST.update.vhist(vhist.children[0], vhist.children[1], u.rear.vhist);
        SST.update.vbands(vhist.children[2], u.rear.vbands);
      }
    },
    plots: function(start, end) {
      const args = "?start=" + start + "&end=" + end;
      m.request({
        method: "GET",
        url: '/api/session/' + Session.current.id + '/filter' + args,
      })
      .then((update) => {
          Session.current.suspension_count == 2 ? SST.update.process_double_json(update) :
                                                  SST.update.process_single_json(update);
      })
      .catch((error) => {
        SST.setError('Invalid range!')
      })
    },
    fft: function(p, u) {
      p.select_one("ds_fft").data = u.data;
      p.select_one("b_fft").glyph.width = 4.9 / u.data.freqs.length
    },
    thist: function(p, u) {
      p.select_one("ds_hist").data = u.data;
      p.y_range.end = u.range_end;

      const s_avg = p.select_one("s_avg");
      if (s_avg) s_avg.location = u.avg;
      const s_max = p.select_one("s_max");
      if (s_max) s_max.location = u.mx;
      const s_p95 = p.select_one("s_p95");
      if (s_p95) s_p95.location = u.p95;

      const l_avg = p.select_one("l_avg_short");
      if (l_avg) l_avg.x = u.avg;
      const l_max = p.select_one("l_max_short");
      if (l_max) l_max.x = u.mx;
      const l_p95 = p.select_one("l_p95_short");
      if (l_p95) l_p95.x = u.p95;

      const tb = p.select_one("stats_textbox");
      if (tb) tb.text = u.stats_textbox_text;
    },
    vhist: function(p, p_lowspeed, u) {
      p.select_one("ds_hist").data = u.data;
      p.x_range.end = u.mx;
      p_lowspeed.select_one("ds_hist_lowspeed").data = u.data_lowspeed;
      p_lowspeed.x_range.end = u.mx_lowspeed;

      p.select_one("ds_normal").data = u.normal_data;
      p_lowspeed.select_one("ds_normal_lowspeed").data = u.normal_data_lowspeed;

      // Update span locations (null-safe)
      const s_avgr = p.select_one("s_avgr");
      if (s_avgr) s_avgr.location = u.s_avgr_loc;
      const s_maxr = p.select_one("s_maxr");
      if (s_maxr) s_maxr.location = u.s_maxr_loc;
      const s_p95r = p.select_one("s_p95r");
      if (s_p95r) s_p95r.location = u.s_p95r_loc;
      const s_avgc = p.select_one("s_avgc");
      if (s_avgc) s_avgc.location = u.s_avgc_loc;
      const s_maxc = p.select_one("s_maxc");
      if (s_maxc) s_maxc.location = u.s_maxc_loc;
      const s_p95c = p.select_one("s_p95c");
      if (s_p95c) s_p95c.location = u.s_p95c_loc;

      // Update label y positions (null-safe)
      const l_maxr = p.select_one("l_short_maxr");
      if (l_maxr) l_maxr.y = u.l_short_maxr_y;
      const l_p95r = p.select_one("l_short_p95r");
      if (l_p95r) l_p95r.y = u.l_short_p95r_y;
      const l_avgr = p.select_one("l_short_avgr");
      if (l_avgr) l_avgr.y = u.l_short_avgr_y;
      const l_avgc = p.select_one("l_short_avgc");
      if (l_avgc) l_avgc.y = u.l_short_avgc_y;
      const l_p95c = p.select_one("l_short_p95c");
      if (l_p95c) l_p95c.y = u.l_short_p95c_y;
      const l_maxc = p.select_one("l_short_maxc");
      if (l_maxc) l_maxc.y = u.l_short_maxc_y;

      // Update velocity textbox
      const vtb = p.select_one("l_velocity_textbox");
      if (vtb) vtb.text = u.velocity_textbox_text;
    },
    vbands: function(p, u) {
      p.select_one("ds_stats").data = u.data;

      const l_hsr = p.select_one("l_hsr");
      if (l_hsr) { l_hsr.text = u.hsr_text; if (u.y_hsr != null) l_hsr.y = u.y_hsr; }
      const l_lsr = p.select_one("l_lsr");
      if (l_lsr) { l_lsr.text = u.lsr_text; if (u.y_lsr != null) l_lsr.y = u.y_lsr; }
      const l_lsc = p.select_one("l_lsc");
      if (l_lsc) { l_lsc.text = u.lsc_text; if (u.y_lsc != null) l_lsc.y = u.y_lsc; }
      const l_hsc = p.select_one("l_hsc");
      if (l_hsc) { l_hsc.text = u.hsc_text; if (u.y_hsc != null) l_hsc.y = u.y_hsc; }

      p.y_range.end = u.y_range_end;
    },
    balance: function(p, u) {
      p.select_one("ds_f").data = u.f_data;
      p.select_one("ds_r").data = u.r_data;
      p.x_range.end = u.range_end;
    },
    thist_comp: function(p, front_u, rear_u) {
      const ds_front = p.select_one("ds_hist_front_comp");
      const ds_rear = p.select_one("ds_hist_rear_comp");

      // Determine current toggle state from x-axis label
      const is_mm = p.below && p.below.length > 0 &&
                    p.below[0].axis_label &&
                    p.below[0].axis_label.includes('mm');
      const key_mids = is_mm ? 'travel_mids_mm' : 'travel_mids_perc';
      const key_widths = is_mm ? 'bar_widths_mm' : 'bar_widths_perc';

      if (ds_front && front_u && front_u.comp_data) {
        const cd = front_u.comp_data;
        cd['x'] = cd[key_mids].slice();
        cd['w'] = cd[key_widths].slice();
        ds_front.data = cd;
      }
      if (ds_rear && rear_u && rear_u.comp_data) {
        const cd = rear_u.comp_data;
        cd['x'] = cd[key_mids].slice();
        cd['w'] = cd[key_widths].slice();
        ds_rear.data = cd;
      }
      // Adjust y_range to fit both
      var max_y = 1.0;
      if (front_u && front_u.comp_data && front_u.comp_data.time_perc) {
        max_y = Math.max(max_y, Math.max.apply(null, front_u.comp_data.time_perc));
      }
      if (rear_u && rear_u.comp_data && rear_u.comp_data.time_perc) {
        max_y = Math.max(max_y, Math.max.apply(null, rear_u.comp_data.time_perc));
      }
      p.y_range.end = max_y * 1.3;
    },
    map: function(full_track, session_track) {
      const map = Bokeh.documents[0].get_model_by_name("map");
      if (session_track) {
        const start_lon = session_track["lon"][0];
        const start_lat = session_track["lat"][0];

        map.select_one("ds_track").data = full_track;
        map.select_one("ds_session").data = session_track;

        const ratio = map.inner_height / map.inner_width;
        map.x_range.start = start_lon - 600;
        map.x_range.end = start_lon + 600;
        map.y_range.start = start_lat - (600 * ratio);
        map.y_range.end = start_lat + (600 * ratio);

        const start_point = map.select_one("start_point");
        start_point.size = 10
        start_point.x = full_track["lon"][0];
        start_point.y = full_track["lat"][0];

        const end_point = map.select_one("end_point");
        end_point.size = 10
        end_point.x = full_track["lon"].slice(-1)[0];
        end_point.y = full_track["lat"].slice(-1)[0];

        map.select_one("pos_marker").size = 13
      } else {
        // visible = false does not work, so we just set the size to 0
        Bokeh.documents[0].get_model_by_name("start_point").size = 0
        Bokeh.documents[0].get_model_by_name("end_point").size = 0
        Bokeh.documents[0].get_model_by_name("pos_marker").size = 0
      }
    },
  }
}

module.exports = SST
