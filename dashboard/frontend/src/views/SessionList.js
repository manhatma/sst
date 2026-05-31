var m = require("mithril")
var Session = require("../models/Session")
var User = require("../models/User")
var Login = require("./Login")


var SessionDayItem = {
 view: function(vnode) {
    return m("div", {style: "display: block; margin: 5px;"}, [
      m("p", {style: "font-size: 14px; color: #d0d0d0; margin-top: 10px;"}, vnode.children[0]),
      m("hr", {style: "margin-top: 3px;"}),
    ])
  }
}

var SessionListItem = {
  view: function(vnode) {
    var session = vnode.children[0]
    var selected = SessionList.selected.has(session.id)
    return m("div", {style: "display: flex; justify-content: space-between; align-items: center;"}, [
      m("div", {style: "display: flex; align-items: center; min-width: 0;"}, [
        m("input[type=checkbox].compare-check", {
          checked: selected,
          title: "Select for comparison",
          onclick: (e) => {
            e.stopPropagation()
            SessionList.toggle(session.id)
          },
        }),
        m(".tooltip", {style: "display: inline-block; margin: 5px; margin-left: 8px; min-width: 0;"}, [
          m(m.route.Link, {
                style: "display: inline-block;",
                class: "route-link",
                onclick: () => {document.getElementById('drawer-toggle').checked = false;},
                href: "/dashboard/" + session.id
              }, session.name),
          m("span.tooltiptext", session.description != "" ? session.description : "No description")
        ]),
      ]),
      User.current ? m("button.delete-button", {
        onclick: () => {
          SessionList.selected.delete(session.id)
          Session.remove(session.id)
          .catch((e) => {
            if (e.code == 401) {
              Login.forceLogout()
            }
          })
        },
      }, "del") : null,
    ])
  }
}

var SessionList = {
  selected: new Set(),
  toggle: function(id) {
    if (SessionList.selected.has(id)) {
      SessionList.selected.delete(id)
    } else {
      SessionList.selected.add(id)
    }
  },
  startCompare: function() {
    if (SessionList.selected.size < 2) return
    document.getElementById('drawer-toggle').checked = false
    m.route.set("/compare/" + Array.from(SessionList.selected).join(","))
  },
  oninit: Session.loadList,
  view: function() {
    var count = SessionList.selected.size
    return m(".session-list", [
      m(".compare-bar", [
        m("button.compare-button", {
          disabled: count < 2,
          onclick: SessionList.startCompare,
        }, "Compare" + (count > 0 ? " (" + count + ")" : "")),
        count > 0 ? m("button.compare-clear", {
          onclick: () => { SessionList.selected.clear() },
        }, "clear") : null,
      ]),
    ].concat(Object.entries(Session.list).map(function([d, s], i) {
      return m(".session-list-day", [m(SessionDayItem, d)].concat(s.map(function(session) {
        return m(SessionListItem, [session])
      })))
    })))
  },
}

module.exports = SessionList
