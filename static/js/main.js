// Campus Lost & Found: small progressive enhancements.
// Every form also works without JavaScript; the server re-checks everything.
(function () {
  "use strict";

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var CSRF = csrfMeta ? csrfMeta.getAttribute("content") : "";

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRFToken": CSRF
      },
      body: JSON.stringify(body || {}),
      keepalive: true
    }).then(function (res) {
      return res.json().catch(function () { return { ok: false }; });
    });
  }

  // --- Mobile navigation ---
  var nav = document.querySelector(".navbar");
  var toggle = document.querySelector(".nav-toggle");
  if (nav && toggle) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Close <details> dropdowns when clicking elsewhere.
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.dropdown[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });

  // --- Dismissible flash messages ---
  document.querySelectorAll(".alert-close").forEach(function (btn) {
    btn.addEventListener("click", function () { btn.closest(".alert").remove(); });
  });

  // --- Confirm before destructive actions: <form data-confirm="..."> ---
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
    });
  });

  // --- OTP input: digits only ---
  document.querySelectorAll(".otp-input").forEach(function (input) {
    input.addEventListener("input", function () {
      input.value = input.value.replace(/\D/g, "").slice(0, 6);
    });
  });

  // --- Resend OTP with a 60-second countdown ---
  var resendForm = document.querySelector("form[data-resend]");
  if (resendForm) {
    var button = resendForm.querySelector("button");
    var label = button.textContent;
    var status = document.querySelector("[data-resend-status]");
    var timer = null;

    var startCountdown = function (seconds) {
      clearInterval(timer);
      var left = parseInt(seconds, 10) || 0;
      var tick = function () {
        if (left <= 0) {
          clearInterval(timer);
          button.disabled = false;
          button.textContent = label;
          return;
        }
        button.disabled = true;
        button.textContent = "Resend in " + left + "s";
        left -= 1;
      };
      tick();
      timer = setInterval(tick, 1000);
    };

    startCountdown(resendForm.getAttribute("data-cooldown"));

    resendForm.addEventListener("submit", function (e) {
      e.preventDefault();
      button.disabled = true;
      postJSON(resendForm.getAttribute("action"), { purpose: resendForm.getAttribute("data-purpose") })
        .then(function (data) {
          if (status) {
            status.textContent = data.message || "Something went wrong. Refresh and try again.";
          }
          startCountdown(data.cooldown || 0);
        })
        .catch(function () { resendForm.submit(); });
    });
  }

  // --- Live password checklist ---
  document.querySelectorAll("input[data-rules]").forEach(function (input) {
    var list = document.getElementById(input.getAttribute("data-rules"));
    if (!list) return;
    var rules = {
      length: function (v) { return v.length >= 8; },
      upper: function (v) { return /[A-Z]/.test(v); },
      number: function (v) { return /[0-9]/.test(v); },
      special: function (v) { return /[^A-Za-z0-9\s]/.test(v); }
    };
    var update = function () {
      list.querySelectorAll("[data-rule]").forEach(function (li) {
        var ok = rules[li.getAttribute("data-rule")](input.value);
        li.classList.toggle("ok", ok);
      });
    };
    input.addEventListener("input", update);
    update();
  });

  // --- Image inputs: check type/size early and preview the photo ---
  var MAX_BYTES = 5 * 1024 * 1024;
  var TYPES = ["image/jpeg", "image/png", "image/webp"];
  document.querySelectorAll('input[type="file"][data-image]').forEach(function (input) {
    var preview = input.id ? document.querySelector('[data-preview="' + input.id + '"]') : null;
    var maxFiles = parseInt(input.getAttribute("data-maxfiles") || "1", 10);
    input.addEventListener("change", function () {
      var files = Array.prototype.slice.call(input.files || []);
      var problem = "";
      if (files.length > maxFiles) problem = "Choose at most " + maxFiles + " images.";
      files.forEach(function (f) {
        if (TYPES.indexOf(f.type) === -1) problem = "Only JPG, PNG or WEBP images are allowed.";
        else if (f.size > MAX_BYTES) problem = "“" + f.name + "” is larger than 5 MB.";
      });
      input.setCustomValidity(problem);
      if (problem) input.reportValidity();
      if (preview) {
        if (!problem && files[0]) {
          preview.src = URL.createObjectURL(files[0]);
          preview.classList.add("show");
        } else {
          preview.classList.remove("show");
          preview.removeAttribute("src");
        }
      }
    });
  });

  // --- Notifications: mark as read when opened ---
  var bellCount = document.querySelector(".bell-count");
  function setUnread(n) {
    if (!bellCount) return;
    if (n > 0) bellCount.textContent = n > 99 ? "99+" : n;
    else bellCount.remove();
  }
  document.querySelectorAll("a[data-notification]").forEach(function (link) {
    link.addEventListener("click", function () {
      var row = link.closest(".notif");
      if (!row || !row.classList.contains("unread")) return;
      postJSON(link.getAttribute("data-read-url")).then(function (data) {
        if (data && data.ok) setUnread(data.unread);
      });
      row.classList.remove("unread");
    });
  });
  document.querySelectorAll("form[data-read-form]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      postJSON(form.getAttribute("action")).then(function (data) {
        if (!data || !data.ok) return form.submit();
        setUnread(data.unread);
        var row = form.closest(".notif");
        if (row) {
          row.classList.remove("unread");
          form.remove();
          var dot = row.querySelector(".unread-dot");
          if (dot) dot.remove();
        } else {
          document.querySelectorAll(".notif.unread").forEach(function (r) {
            r.classList.remove("unread");
            var d = r.querySelector(".unread-dot");
            if (d) d.remove();
            var f = r.querySelector("form[data-read-form]");
            if (f) f.remove();
          });
          form.remove();
        }
      });
    });
  // --- Password visibility toggle (eye icon) ---
  document.querySelectorAll(".password-toggle").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var wrap = btn.closest(".password-input-group");
      if (!wrap) return;
      var input = wrap.querySelector("input");
      if (!input) return;

      var isText = input.type === "text";
      input.type = isText ? "password" : "text";
      btn.classList.toggle("is-visible", !isText);
      btn.setAttribute("aria-label", isText ? "Show password" : "Hide password");
    });
  });
})();

