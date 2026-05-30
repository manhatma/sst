var m = require("mithril")
var Login = require("./Login")

// Wait until every Bokeh placeholder div is in the DOM before eval-ing the
// embed script (same pattern as Dashboard.js).
function waitForDivs(divIds, callback) {
  if (divIds.length === 0) { callback(); return; }
  const seen = new Set();
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE && divIds.includes(node.id)) {
          seen.add(node.id);
          if (seen.size === divIds.length) {
            callback();
            observer.disconnect();
          }
        }
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

var Compare = {
  data: null,
  error: "",
  oncreate: function(vnode) {
    Compare.data = null;
    Compare.error = "";
    m.request({
      method: "GET",
      url: "/api/session/compare?ids=" + encodeURIComponent(vnode.attrs.ids),
    })
    .then(function(result) {
      Compare.data = result;
      Compare.divIds = result.figures
        .map((f) => f.div.split('"')[1])
        .filter((id) => !!id);
      m.redraw();
      waitForDivs(Compare.divIds, () => { eval(Compare.data.script); });
    })
    .catch(function(error) {
      Compare.error = (error.response && error.response.msg) || "Comparison failed";
      if (error.code == 401) { Login.forceLogout(); }
      m.redraw();
    });
  },
  onremove: function() {
    if (typeof Bokeh !== "undefined" && Bokeh.documents && Bokeh.documents.length != 0) {
      Bokeh.documents[0].clear();
      delete Bokeh.documents[0];
      Bokeh.documents.splice(0);
    }
    Compare.data = null;
    document.getElementById("layout-stylesheet").setAttribute("href", "");
  },
  view: function() {
    if (Compare.error) {
      return m(".compare-container", m(".compare-error", Compare.error));
    }
    if (!Compare.data) {
      return m(".compare-container", "LOADING COMPARISON");
    }
    return m(".compare-container", [
      m(".compare-legend", Compare.data.sessions.map((s) =>
        m("span.compare-legend-item", { style: "color:" + s.color }, "■ " + s.name))),
      m(".compare-grid", Compare.data.figures.map((f) =>
        m(".compare-cell", [
          m(".compare-cell-title", f.title),
          m(".compare-cell-plot", m.trust(f.div)),
        ]))),
    ]);
  },
};

module.exports = Compare;
