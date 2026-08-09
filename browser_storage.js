(function () {
  "use strict";
  if (window.__sopBridgeLoaded) return;
  window.__sopBridgeLoaded = true;

  var SESSION_KEY = "sop.session";
  var STATE_KEY = "sop.steps";

  var session = {
    id: null,
    startedAt: null,
    origin: window.location.origin
  };

  function newSessionId() {
    return "sop-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
  }

  function loadSession() {
    try {
      var raw = window.localStorage.getItem(SESSION_KEY);
      if (raw) {
        session = JSON.parse(raw);
      }
    } catch (err) {}
    if (!session || !session.id) {
      session = { id: newSessionId(), startedAt: Date.now(), url: window.location.href };
      persist();
    }
  }

  function loadSteps() {
    try {
      var raw = window.localStorage.getItem(STATE_KEY);
      var arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (err) {
      return [];
    }
  }

  function persist() {
    try {
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    } catch (err) {}
  }

  function persistSteps(steps) {
    try {
      window.localStorage.setItem(STATE_KEY, JSON.stringify(steps));
    } catch (err) {}
  }

  function cssPath(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return "#" + el.id;
    var parts = [];
    var node = el;
    while (node && node.nodeType === 1 && parts.length < 16) {
      var part = node.tagName.toLowerCase();
      if (node.id) {
        part = "#" + node.id;
        parts.unshift(part);
        break;
      }
      if (node.className && typeof node.className === "string") {
        var cls = node.className.split(/\s+/).filter(Boolean).slice(0, 3).join(".");
        if (cls) part += "." + cls;
      }
      var parent = node.parentElement;
      if (parent) {
        var same = Array.prototype.slice.call(parent.children).filter(function (c) {
          return c.tagName === node.tagName;
        });
        if (same.length > 1) {
          part += ":nth-of-type(" + (same.indexOf(node) + 1) + ")";
        }
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(" > ");
  }

  function track(eventType, target) {
    var steps = loadSteps();
    steps.push({
      type: eventType,
      selector: cssPath(target),
      tag: target ? target.tagName : null,
      text: target && target.innerText ? target.innerText.slice(0, 120) : null,
      url: window.location.href,
      ts: Date.now()
    });
    persistSteps(steps);
  }

  document.addEventListener(
    "click",
    function (ev) {
      var t = ev.target;
      while (t && t.nodeType !== 1) t = t.parentElement;
      if (!t) return;
      track("click", t);
    },
    true
  );

  document.addEventListener(
    "input",
    function (ev) {
      var t = ev.target;
      while (t && t.nodeType !== 1) t = t.parentElement;
      if (!t) return;
      var tag = (t.tagName || "").toLowerCase();
      var value = null;
      if (tag === "input" || tag === "textarea" || tag === "select") {
        value = t.value;
      }
      track("input", t);
      var steps = loadSteps();
      var last = steps[steps.length - 1];
      if (last && typeof value === "string") last.value = value.slice(0, 240);
      persistSteps(steps);
    },
    true
  );

  window.__sopInfo = function () {
    loadSession();
    return {
      sessionId: session.id,
      startedAt: session.startedAt,
      stepCount: loadSteps().length
    };
  };

  window.__sopGet = function () {
    return loadSteps();
  };

  window.__sopReset = function () {
    try {
      window.localStorage.removeItem(STATE_KEY);
      window.localStorage.removeItem(SESSION_KEY);
    } catch (err) {}
    session = { id: newSessionId(), startedAt: Date.now(), url: window.location.href };
    persist();
    return window.__sopGet();
  };

  loadSession();
})();