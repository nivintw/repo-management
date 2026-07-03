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
  // The stored choice is applied before first paint by an inline <head> script on every
  // page (avoiding a wrong-theme flash); this file only handles the toggle itself.
  var root = document.documentElement;

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
    var runSearch = function () {
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
    };
    input.addEventListener("input", runSearch);
    // Re-show results when the user clicks back into a non-empty search box (the
    // outside-click handler below hides them).
    input.addEventListener("focus", runSearch);
    document.addEventListener("click", function (event) {
      if (results && !results.contains(event.target) && event.target !== input) {
        results.hidden = true;
      }
    });
  }
})();
