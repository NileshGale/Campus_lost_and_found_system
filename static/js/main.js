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
  document.querySelectorAll(".flash-stack .alert:not(.alert-error)").forEach(function (alert) {
    window.setTimeout(function () {
      if (alert && alert.parentNode) alert.remove();
    }, 8000);
  });

  // --- In-app confirm dialog (replaces window.confirm) ---
  var modal = document.getElementById("confirm-modal");
  var modalTitle = document.getElementById("confirm-title");
  var modalMessage = document.getElementById("confirm-message");
  var modalOk = document.getElementById("confirm-ok");
  var lastFocus = null;
  var confirmResolver = null;

  function setModalOpen(open) {
    if (!modal) return;
    document.body.classList.toggle("modal-open", open);
    if (open) {
      lastFocus = document.activeElement;
      modal.hidden = false;
      modal.removeAttribute("hidden");
      document.querySelectorAll("details.dropdown[open]").forEach(function (d) {
        d.removeAttribute("open");
      });
      var cancelBtn = modal.querySelector(".modal-dialog [data-modal-dismiss]");
      window.setTimeout(function () { (cancelBtn || modalOk).focus(); }, 0);
    } else {
      modal.hidden = true;
      modal.setAttribute("hidden", "");
      if (modalOk) {
        modalOk.classList.remove("btn-danger-solid");
        modalOk.classList.add("btn-primary");
      }
      if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
    }
  }

  function closeConfirm(result) {
    var resolve = confirmResolver;
    confirmResolver = null;
    setModalOpen(false);
    if (resolve) resolve(!!result);
  }

  function openConfirm(opts) {
    if (!modal || !modalTitle || !modalMessage || !modalOk) {
      return Promise.resolve(window.confirm((opts.title ? opts.title + " " : "") + (opts.message || "")));
    }
    if (confirmResolver) closeConfirm(false);
    modalTitle.textContent = opts.title || "Please confirm";
    modalMessage.textContent = opts.message || "";
    modalOk.textContent = opts.okLabel || "Confirm";
    if (opts.danger) {
      modalOk.classList.remove("btn-primary");
      modalOk.classList.add("btn-danger-solid");
    } else {
      modalOk.classList.remove("btn-danger-solid");
      modalOk.classList.add("btn-primary");
    }
    setModalOpen(true);
    return new Promise(function (resolve) { confirmResolver = resolve; });
  }

  if (modal) {
    modal.addEventListener("click", function (e) {
      if (e.target.closest("[data-modal-dismiss]")) closeConfirm(false);
    });
    modalOk.addEventListener("click", function () { closeConfirm(true); });
    document.addEventListener("keydown", function (e) {
      if (modal.hidden) return;
      if (e.key === "Escape") {
        e.preventDefault();
        closeConfirm(false);
        return;
      }
      if (e.key !== "Tab") return;
      var focusable = modal.querySelectorAll("button:not([disabled])");
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });
  }

  function confirmAttrs(el) {
    if (!el) return null;
    var message = el.getAttribute("data-confirm");
    if (!message) return null;
    return {
      message: message,
      title: el.getAttribute("data-confirm-title") || "Please confirm",
      okLabel: el.getAttribute("data-confirm-ok") || "Confirm",
      danger: el.hasAttribute("data-danger")
    };
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.getAttribute("data-confirmed") === "1") {
      form.removeAttribute("data-confirmed");
      return;
    }
    var submitter = e.submitter || document.activeElement;
    var opts = confirmAttrs(submitter) || confirmAttrs(form);
    if (!opts) return;
    e.preventDefault();
    openConfirm(opts).then(function (ok) {
      if (!ok) return;
      form.setAttribute("data-confirmed", "1");
      if (typeof form.requestSubmit === "function") form.requestSubmit(submitter instanceof HTMLElement ? submitter : undefined);
      else form.submit();
    });
  });

  // --- Copy to clipboard ---
  function toast(message) {
    var host = document.getElementById("toast-host");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.textContent = message;
    host.appendChild(el);
    window.setTimeout(function () {
      el.classList.add("hide");
      window.setTimeout(function () { el.remove(); }, 280);
    }, 2800);
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    e.preventDefault();
    var text = btn.getAttribute("data-copy") || "";
    var label = btn.querySelector("[data-copy-text]") || btn;
    var original = label.textContent;
    var done = function () {
      label.textContent = "Copied";
      toast("Link copied");
      window.setTimeout(function () { label.textContent = original; }, 1800);
    };
    var fail = function () { toast("Could not copy. Select the address bar instead."); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(fail);
    } else {
      fail();
    }
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
  var passwordRules = {
    length: function (v) { return (v || "").length >= 8; },
    upper: function (v) { return /[A-Z]/.test(v || ""); },
    number: function (v) { return /[0-9]/.test(v || ""); },
    special: function (v) { return /[^A-Za-z0-9\s]/.test(v || ""); }
  };

  function bindPasswordRules(input, list) {
    if (!input || !list || input.dataset.rulesBound) return;
    input.dataset.rulesBound = "1";
    var update = function () {
      var val = input.value || "";
      list.querySelectorAll("[data-rule]").forEach(function (li) {
        var ruleName = li.getAttribute("data-rule");
        var ok = passwordRules[ruleName] ? passwordRules[ruleName](val) : false;
        li.classList.toggle("ok", ok);
      });
    };
    ["input", "keyup", "change", "paste"].forEach(function (evt) {
      input.addEventListener(evt, update);
    });
    update();
  }

  document.querySelectorAll("input[data-rules]").forEach(function (input) {
    bindPasswordRules(input, document.getElementById(input.getAttribute("data-rules")));
  });
  document.querySelectorAll(".password-rules").forEach(function (list) {
    var group = list.closest(".form-group");
    var input = group ? group.querySelector("input") : null;
    bindPasswordRules(input, list);
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
        if (preview.dataset.objectUrl) {
          URL.revokeObjectURL(preview.dataset.objectUrl);
          delete preview.dataset.objectUrl;
        }
        if (!problem && files[0]) {
          var objectUrl = URL.createObjectURL(files[0]);
          preview.dataset.objectUrl = objectUrl;
          preview.src = objectUrl;
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
  });

  // --- Password visibility toggle (eye icon) ---
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".password-toggle");
    if (!btn) return;
    e.preventDefault();
    var wrap = btn.closest(".password-input-group");
    if (!wrap) return;
    var input = wrap.querySelector("input");
    if (!input) return;

    var hide = input.type === "text";
    input.type = hide ? "password" : "text";
    btn.classList.toggle("is-visible", !hide);
    btn.setAttribute("aria-label", hide ? "Show password" : "Hide password");
  });
})();

