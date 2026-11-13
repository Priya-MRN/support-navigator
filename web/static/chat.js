/* Support Assistant client.
 *
 * Talks to /api/message and renders the engine's flow: an intake gate, bot
 * bubbles with structured numbered steps, quick-reply chips, an escalation
 * form, and a ticket confirmation card.
 *
 * Layout adapts on the SHELL's own width via ResizeObserver (not the viewport)
 * so the component behaves correctly embedded in a widget, modal or iframe.
 */
(function () {
  "use strict";

  var app = document.getElementById("app");
  var thread = document.getElementById("thread");
  var scroller = document.getElementById("scroller");
  var replies = document.getElementById("replies");
  var composer = document.getElementById("composer");
  var draft = document.getElementById("draft");
  var topicsBtn = document.getElementById("topics-btn");
  var restartBtn = document.getElementById("restart-btn");
  var railHumanBtn = document.getElementById("rail-human-btn");

  var WIDE_AT = 900;
  var TYPING_MS = 520;

  var sessionId = null;
  var state = {
    gated: true,       // intake gate is up
    topic: "General",
    user: null,        // {name, email} once intake completes
    busy: false,
  };
  var typingEl = null;
  var typingTimer = null;

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- utils */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  /** Build an <svg class="icon"><use href="#i-name"></svg> node. */
  function icon(name, cls) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", cls ? "icon " + cls : "icon");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    // Both attributes: href for modern browsers, xlink:href for older ones.
    use.setAttribute("href", "#i-" + name);
    use.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function scrollToLatest() {
    scroller.scrollTo({
      top: scroller.scrollHeight,
      behavior: reducedMotion ? "auto" : "smooth",
    });
  }

  function validEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value);
  }

  /* ------------------------------------------------- modal card behaviour */

  /* The intake and contact cards block the composer, so they behave like
   * modals: Escape dismisses them, Tab is trapped inside while they are open,
   * and focus returns to whatever opened them on close. */
  var activeCard = null;

  var FOCUSABLE = [
    "a[href]", "button:not([disabled])", "input:not([disabled])",
    "textarea:not([disabled])", "select:not([disabled])", "[tabindex]",
  ].join(",");

  function focusableIn(root) {
    return Array.prototype.filter.call(
      root.querySelectorAll(FOCUSABLE),
      function (node) {
        // Skip anything hidden or explicitly removed from the tab order.
        return node.tabIndex !== -1 && node.offsetParent !== null;
      }
    );
  }

  /**
   * Register a blocking card. `onDismiss` runs when Escape is pressed; pass
   * null for a card that must not be dismissible.
   */
  function openCard(card, onDismiss) {
    closeCard();
    activeCard = {
      el: card,
      onDismiss: onDismiss,
      // Restore focus here on close — usually the button that opened the card.
      returnTo: document.activeElement,
    };
    card.setAttribute("role", "group");
    card.setAttribute("aria-modal", "true");
  }

  /** Tear down the active card and restore focus to its trigger. */
  function closeCard() {
    if (!activeCard) return;
    var returnTo = activeCard.returnTo;
    activeCard = null;
    // Only restore to something still in the document and focusable.
    if (returnTo && document.contains(returnTo) && !returnTo.disabled) {
      try { returnTo.focus(); } catch (err) { /* non-focusable; ignore */ }
    }
  }

  /** Remove a card from the DOM and release the trap in one step. */
  function dismissCard(card) {
    if (card && card.parentNode) card.remove();
    closeCard();
  }

  document.addEventListener("keydown", function (e) {
    if (!activeCard) return;

    if (e.key === "Escape") {
      // A card whose dismissal needs a server round-trip owns that call.
      if (activeCard.onDismiss) {
        e.preventDefault();
        activeCard.onDismiss();
      }
      return;
    }

    if (e.key !== "Tab") return;

    var items = focusableIn(activeCard.el);
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];

    // Wrap at both ends, and pull focus back in if it escaped the card.
    if (!activeCard.el.contains(document.activeElement)) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });

  /* ------------------------------------------------------------ messages */

  function addUser(text) {
    var wrap = el("div", "msg msg-user");
    wrap.appendChild(el("div", "bubble-user", text));
    thread.appendChild(wrap);
    scrollToLatest();
  }

  /**
   * Render a bot message: lead paragraph, optional numbered steps, optional
   * tail line, optional ticket success card.
   */
  function addBot(data) {
    var wrap = el("div", "msg msg-bot");

    var who = el("span", "msg-who");
    who.appendChild(icon("bot"));
    who.appendChild(el("span", null, "Assistant"));
    wrap.appendChild(who);

    var bubble = el("div", "bubble-bot");

    if (data.message) {
      bubble.appendChild(el("p", "msg-text", data.message));
    }

    if (data.steps && data.steps.length) {
      var ol = el("ol", "steps");
      data.steps.forEach(function (step, i) {
        var li = el("li");
        li.appendChild(el("span", "step-n", String(i + 1)));
        li.appendChild(el("span", "step-text", step));
        ol.appendChild(li);
      });
      bubble.appendChild(ol);
    }

    var meta = data.meta || {};
    if (meta.ticket_title) {
      var card = el("div", "ticket-card");
      card.appendChild(icon("circle-check-big"));
      var inner = el("div");
      inner.appendChild(el("div", "ticket-card-title", meta.ticket_title));
      if (meta.ticket_meta) {
        inner.appendChild(el("div", "ticket-card-meta", meta.ticket_meta));
      }
      card.appendChild(inner);
      bubble.appendChild(card);
    }

    if (data.tail) {
      bubble.appendChild(el("p", "msg-tail", data.tail));
    }

    wrap.appendChild(bubble);
    thread.appendChild(wrap);
    scrollToLatest();
  }

  function showTyping() {
    hideTyping();
    typingEl = el("div", "msg typing");
    typingEl.setAttribute("aria-hidden", "true");
    var bubble = el("div", "typing-bubble");
    bubble.appendChild(el("span"));
    bubble.appendChild(el("span"));
    bubble.appendChild(el("span"));
    typingEl.appendChild(bubble);
    thread.appendChild(typingEl);
    scrollToLatest();
  }

  function hideTyping() {
    if (typingTimer) {
      window.clearTimeout(typingTimer);
      typingTimer = null;
    }
    if (typingEl && typingEl.parentNode) {
      typingEl.parentNode.removeChild(typingEl);
    }
    typingEl = null;
  }

  /** Show the typing indicator, then render the bot reply. */
  function botSay(data, done) {
    if (reducedMotion) {
      addBot(data);
      if (done) done();
      return;
    }
    showTyping();
    typingTimer = window.setTimeout(function () {
      hideTyping();
      addBot(data);
      if (done) done();
    }, TYPING_MS);
  }

  /* ------------------------------------------------------- quick replies */

  function clearReplies() {
    replies.innerHTML = "";
  }

  /** Classify an option id into the design's plain / yes / no chip styles. */
  function chipKind(optionId) {
    if (optionId === "__yes__") return "yes";
    if (optionId === "__no__") return "no";
    return "plain";
  }

  function renderReplies(options) {
    clearReplies();
    if (!options || !options.length) return;

    options.forEach(function (opt) {
      var kind = chipKind(opt.id);
      var btn = el("button", "chip" + (kind === "plain" ? "" : " chip-" + kind));
      btn.type = "button";

      if (kind === "yes") {
        btn.appendChild(icon("thumbs-up"));
        btn.appendChild(el("span", null, opt.label));
      } else if (kind === "no") {
        btn.appendChild(icon("thumbs-down"));
        btn.appendChild(el("span", null, opt.label));
      } else {
        btn.appendChild(el("span", null, opt.label));
        btn.appendChild(icon("chevron-right"));
      }

      btn.addEventListener("click", function () {
        addUser(opt.label);
        clearReplies();
        sendOption(opt.id);
      });
      replies.appendChild(btn);
    });
  }

  /* -------------------------------------------------------- intake gate */

  /** Render the "Who am I helping?" card into the thread. */
  function renderIntake(errorText) {
    var card = el("div", "card");
    card.id = "intake-card";

    var head = el("div", "card-head");
    head.appendChild(icon("user-round-check"));
    head.appendChild(el("div", "card-title", "Who am I helping?"));
    head.appendChild(el("span", "card-step", "Step 1 of 2"));
    card.appendChild(head);

    var grid = el("div", "field-grid");

    var nameField = el("div", "field");
    var nameLabel = el("label", null, "Your name");
    nameLabel.setAttribute("for", "intake-name");
    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.id = "intake-name";
    nameInput.placeholder = "e.g. Alex Morgan";
    nameInput.autocomplete = "name";
    nameField.appendChild(nameLabel);
    nameField.appendChild(nameInput);

    var emailField = el("div", "field");
    var emailLabel = el("label", null, "Your email");
    emailLabel.setAttribute("for", "intake-email");
    var emailInput = el("input");
    emailInput.type = "email";
    emailInput.id = "intake-email";
    emailInput.placeholder = "you@example.com";
    emailInput.autocomplete = "email";
    emailField.appendChild(emailLabel);
    emailField.appendChild(emailInput);

    grid.appendChild(nameField);
    grid.appendChild(emailField);
    card.appendChild(grid);

    var errorBox = el("div", "form-error");
    errorBox.id = "intake-error";
    errorBox.setAttribute("role", "alert");
    errorBox.hidden = true;
    errorBox.appendChild(icon("circle-alert"));
    errorBox.appendChild(el("span"));
    card.appendChild(errorBox);

    var actions = el("div", "card-actions");
    var startBtn = el("button", "btn-primary");
    startBtn.type = "button";
    startBtn.appendChild(el("span", null, "Start chat"));
    startBtn.appendChild(icon("arrow-right"));

    var skipBtn = el("button", "btn-secondary", "Skip for now");
    skipBtn.type = "button";

    actions.appendChild(startBtn);
    actions.appendChild(skipBtn);
    actions.appendChild(
      el("span", "card-note", "So an expert can follow up without asking twice")
    );
    card.appendChild(actions);

    function showError(msg) {
      // Never reveal an empty box — an icon with no text reads as a glitch.
      if (!msg) {
        errorBox.hidden = true;
        return;
      }
      errorBox.querySelector("span").textContent = msg;
      errorBox.hidden = false;
    }
    if (errorText) showError(errorText);

    function submit() {
      var name = nameInput.value.trim();
      var email = emailInput.value.trim();
      // Validate client-side for instant feedback; the server re-validates.
      if (!name) {
        showError("Please add your name so I know who I'm helping.");
        nameInput.setAttribute("aria-invalid", "true");
        nameInput.focus();
        return;
      }
      nameInput.removeAttribute("aria-invalid");
      if (!validEmail(email)) {
        showError("That email doesn't look right — please double-check it.");
        emailInput.setAttribute("aria-invalid", "true");
        emailInput.focus();
        return;
      }
      emailInput.removeAttribute("aria-invalid");
      errorBox.hidden = true;

      state.user = { name: name, email: email };
      dismissCard(card);
      addUser(name + " · " + email);
      post({ action: "intake", name: name, email: email }).then(handleResponse);
    }

    function skip() {
      dismissCard(card);
      post({ action: "skip_intake" }).then(handleResponse);
    }

    startBtn.addEventListener("click", submit);
    skipBtn.addEventListener("click", skip);

    // Enter submits from either field.
    [nameInput, emailInput].forEach(function (input) {
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          submit();
        }
      });
    });

    thread.appendChild(card);
    // Escape on the intake gate is equivalent to "Skip for now".
    openCard(card, skip);
    card.setAttribute("aria-label", "Who am I helping?");
    scrollToLatest();
    window.setTimeout(function () { nameInput.focus(); }, 60);
  }

  /* ---------------------------------------------------- escalation form */

  /** Render the "Connect with a human expert" card into the thread. */
  function renderContactForm(meta) {
    var prefill = (meta && meta.prefill) || state.user || {};
    var topic = (meta && meta.topic) || state.topic;

    var card = el("div", "card");
    card.id = "contact-card";

    var head = el("div", "card-head");
    head.appendChild(icon("headset"));
    head.appendChild(el("div", "card-title", "Connect with a human expert"));
    head.appendChild(el("span", "card-step", topic));
    card.appendChild(head);

    var grid = el("div", "field-grid");

    var nameField = el("div", "field");
    var nameLabel = el("label", null, "Your name");
    nameLabel.setAttribute("for", "contact-name");
    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.id = "contact-name";
    nameInput.placeholder = "e.g. Alex Morgan";
    nameInput.autocomplete = "name";
    nameInput.value = prefill.name || "";
    nameField.appendChild(nameLabel);
    nameField.appendChild(nameInput);

    var emailField = el("div", "field");
    var emailLabel = el("label", null, "Your email");
    emailLabel.setAttribute("for", "contact-email");
    var emailInput = el("input");
    emailInput.type = "email";
    emailInput.id = "contact-email";
    emailInput.placeholder = "you@example.com";
    emailInput.autocomplete = "email";
    emailInput.value = prefill.email || "";
    emailField.appendChild(emailLabel);
    emailField.appendChild(emailInput);

    grid.appendChild(nameField);
    grid.appendChild(emailField);
    card.appendChild(grid);

    var msgField = el("div", "field mt");
    var msgLabel = el("label", null, "How can we help?");
    msgLabel.setAttribute("for", "contact-message");
    var msgInput = el("textarea");
    msgInput.id = "contact-message";
    msgInput.rows = 3;
    msgInput.placeholder = "Briefly describe your issue";
    msgField.appendChild(msgLabel);
    msgField.appendChild(msgInput);
    card.appendChild(msgField);

    var errorBox = el("div", "form-error");
    errorBox.setAttribute("role", "alert");
    errorBox.hidden = true;
    errorBox.appendChild(icon("circle-alert"));
    errorBox.appendChild(el("span"));
    card.appendChild(errorBox);

    var actions = el("div", "card-actions");
    var submitBtn = el("button", "btn-primary");
    submitBtn.type = "button";
    submitBtn.appendChild(icon("send"));
    var submitLabel = el("span", null, "Submit request");
    submitBtn.appendChild(submitLabel);

    var cancelBtn = el("button", "btn-secondary", "Keep chatting");
    cancelBtn.type = "button";

    actions.appendChild(submitBtn);
    actions.appendChild(cancelBtn);
    actions.appendChild(
      el("span", "card-note", "Creates a support ticket · reply within 1 business day")
    );
    card.appendChild(actions);

    function showError(msg) {
      if (!msg) {
        errorBox.hidden = true;
        return;
      }
      errorBox.querySelector("span").textContent = msg;
      errorBox.hidden = false;
    }

    submitBtn.addEventListener("click", function () {
      var name = nameInput.value.trim();
      var email = emailInput.value.trim();
      var message = msgInput.value.trim();

      if (!name) {
        showError("Please add your name so we know who to reply to.");
        nameInput.setAttribute("aria-invalid", "true");
        nameInput.focus();
        return;
      }
      nameInput.removeAttribute("aria-invalid");
      if (!validEmail(email)) {
        showError("That email doesn't look right — please double-check it.");
        emailInput.setAttribute("aria-invalid", "true");
        emailInput.focus();
        return;
      }
      emailInput.removeAttribute("aria-invalid");
      if (!message) {
        showError("A short description helps the expert prepare before replying.");
        msgInput.setAttribute("aria-invalid", "true");
        msgInput.focus();
        return;
      }
      msgInput.removeAttribute("aria-invalid");
      errorBox.hidden = true;

      submitBtn.setAttribute("aria-busy", "true");
      submitBtn.disabled = true;
      submitLabel.textContent = "Sending…";

      post({
        action: "contact",
        name: name,
        email: email,
        message: message,
      }).then(function (data) {
        submitBtn.removeAttribute("aria-busy");
        submitBtn.disabled = false;
        submitLabel.textContent = "Submit request";

        // A validation failure keeps us on the form.
        if (data.input_type === "contact_form") {
          showError(data.message);
          return;
        }
        state.user = { name: name, email: email };
        dismissCard(card);
        addUser("Sent my details: " + name + " (" + email + ")");
        handleResponse(data);
      });
    });

    function cancel() {
      dismissCard(card);
      // Return to the topic menu without creating a ticket.
      post({ action: "option", option_id: "__menu__" }).then(handleResponse);
    }

    cancelBtn.addEventListener("click", cancel);

    thread.appendChild(card);
    // Escape on the escalation form is equivalent to "Keep chatting".
    openCard(card, cancel);
    card.setAttribute("aria-label", "Connect with a human expert");
    scrollToLatest();
    window.setTimeout(function () {
      (prefill.name ? msgInput : nameInput).focus();
    }, 60);
  }

  /* --------------------------------------------------------- networking */

  function post(body, url) {
    body.session_id = sessionId;
    return fetch(url || "/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (res) { return res.json(); })
      .catch(function () {
        hideTyping();
        addBot({
          message:
            "I couldn't reach the server just then. Please check your " +
            "connection and try again.",
        });
        return null;
      });
  }

  function sendOption(optionId) {
    post({ action: "option", option_id: optionId }).then(handleResponse);
  }

  function sendText(text) {
    post({ action: "text", text: text }).then(handleResponse);
  }

  /** Apply a server response: render the reply, then the next input state. */
  function handleResponse(data) {
    if (!data) return;
    sessionId = data.session_id || sessionId;

    if (data.meta && data.meta.topic) state.topic = data.meta.topic;

    // The intake gate is a card, not a chat bubble — it has its own path.
    if (data.input_type === "intake_form") {
      setGated(true);
      clearReplies();
      // A validation error comes back with meta.error; re-render with it.
      // Drop the stale trap WITHOUT restoring focus — renderIntake re-opens a
      // fresh card immediately and focuses its first field.
      var existing = document.getElementById("intake-card");
      if (existing) {
        if (activeCard && activeCard.el === existing) activeCard = null;
        existing.remove();
      }
      if (data.meta && data.meta.error) {
        renderIntake(data.message);
      } else {
        botSay({ message: data.message }, function () { renderIntake(null); });
      }
      return;
    }

    setGated(false);

    botSay(data, function () {
      if (data.input_type === "contact_form") {
        clearReplies();
        renderContactForm(data.meta);
      } else {
        renderReplies(data.options);
        if (!isNarrow()) draft.focus();
      }
    });
  }

  /* ------------------------------------------------------------- layout */

  function isNarrow() {
    return app.classList.contains("is-narrow");
  }

  /** Toggle the composer's gated (dimmed + inert) state. */
  function setGated(gated) {
    state.gated = gated;
    app.classList.toggle("is-gated", gated);
    draft.disabled = gated;
    // Keep the gated composer out of the tab order entirely.
    composer.querySelectorAll("button").forEach(function (b) {
      b.disabled = gated;
    });
    // Only advertise the "why is this disabled" note while it's actually
    // disabled — otherwise every focus on a working composer reads it out.
    var described = composer.querySelectorAll("[data-gate-describes]");
    described.forEach(function (node) {
      if (gated) {
        node.setAttribute("aria-describedby", "composer-gate-note");
      } else {
        node.removeAttribute("aria-describedby");
      }
    });
  }

  /**
   * Switch layout on the SHELL's width, not the viewport's, so the component
   * adapts correctly when embedded in a narrow container on a wide screen.
   */
  function measure() {
    var w = app.clientWidth || window.innerWidth;
    var wide = w >= WIDE_AT;
    app.classList.toggle("is-wide", wide);
    app.classList.toggle("is-narrow", !wide);
  }

  if (window.ResizeObserver) {
    new ResizeObserver(measure).observe(app);
  }
  window.addEventListener("resize", measure);
  measure();

  /* ------------------------------------------------------------- events */

  composer.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = draft.value.trim();
    if (!text || state.gated) return;
    draft.value = "";
    addUser(text);
    clearReplies();
    sendText(text);
  });

  // Topic buttons in the rail (wide) pick a topic directly.
  document.querySelectorAll(".rail-item").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (state.gated) return;
      var id = btn.getAttribute("data-topic");
      var label = btn.querySelector(".rail-item-label").textContent;
      addUser(label);
      clearReplies();
      sendOption(id);
    });
  });

  // Narrow: the grid button surfaces the topics as quick-reply chips.
  topicsBtn.addEventListener("click", function () {
    if (state.gated) return;
    var options = [];
    document.querySelectorAll(".rail-item").forEach(function (btn) {
      options.push({
        id: btn.getAttribute("data-topic"),
        label: btn.querySelector(".rail-item-label").textContent,
      });
    });
    renderReplies(options);
  });

  railHumanBtn.addEventListener("click", function () {
    if (state.gated) return;
    addUser("I'd like to talk to a human");
    clearReplies();
    sendOption("__human__");
  });

  restartBtn.addEventListener("click", function () {
    hideTyping();
    // Wiping the thread destroys any open card — release the trap first so we
    // don't keep trapping Tab inside a node that no longer exists.
    activeCard = null;
    thread.innerHTML = "";
    clearReplies();
    state.user = null;
    state.topic = "General";
    post({}, "/api/reset").then(handleResponse);
  });

  /* --------------------------------------------------------------- boot */

  post({ action: "start" }).then(handleResponse);
})();
