/*
 * SPDX-FileCopyrightText: © 2026 Tyler Nivin
 * SPDX-License-Identifier: MIT
 */

// Docs-site behavior: theme toggle, client-side search, current-page nav highlight.
// Vanilla JS, no build step. The search index is loaded as a classic script
// (search-index.js -> window.SEARCH_INDEX) rather than fetch(), so it works from
// file:// as well as GitHub Pages.

(function () {
  "use strict";

  // ---- Theme toggle (explicit choice wins over prefers-color-scheme) ----
  var root = document.documentElement;
  var stored = null;
  try {
    stored = localStorage.getItem("docs-theme");
  } catch (e) {
    /* storage unavailable (some file:// contexts); fall back to media query */
  }
  if (stored === "light" || stored === "dark") {
    root.setAttribute("data-theme", stored);
  }

  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var dark =
        root.getAttribute("data-theme") === "dark" ||
        (!root.getAttribute("data-theme") &&
          window.matchMedia("(prefers-color-scheme: dark)").matches);
      var next = dark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("docs-theme", next);
      } catch (e) {
        /* non-persistent is fine */
      }
    });
  }

  // ---- Current-page nav highlight ----
  var here = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".top-nav a").forEach(function (a) {
    if (a.getAttribute("href") === here) {
      a.setAttribute("aria-current", "page");
    }
  });

  // ---- Search over window.SEARCH_INDEX ----
  var input = document.getElementById("search");
  var results = document.getElementById("search-results");
  var index = window.SEARCH_INDEX || [];

  function render(hits, query) {
    if (!results) return;
    results.innerHTML = "";
    if (!query) {
      results.hidden = true;
      return;
    }
    if (hits.length === 0) {
      var none = document.createElement("div");
      none.className = "empty";
      none.textContent = "No matches for “" + query + "”";
      results.appendChild(none);
    }
    hits.slice(0, 12).forEach(function (hit) {
      var a = document.createElement("a");
      a.href = hit.href;
      a.textContent = hit.title;
      var page = document.createElement("span");
      page.className = "hit-page";
      page.textContent = hit.page;
      a.appendChild(page);
      results.appendChild(a);
    });
    results.hidden = false;
  }

  if (input) {
    input.addEventListener("input", function () {
      var raw = input.value.trim();
      var q = raw.toLowerCase();
      var hits = q
        ? index.filter(function (entry) {
            return (
              entry.title.toLowerCase().indexOf(q) !== -1 ||
              (entry.terms || "").toLowerCase().indexOf(q) !== -1
            );
          })
        : [];
      render(hits, raw);
    });
    document.addEventListener("click", function (event) {
      if (results && !results.contains(event.target) && event.target !== input) {
        results.hidden = true;
      }
    });
  }
})();
