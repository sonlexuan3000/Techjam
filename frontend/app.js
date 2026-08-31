const state = {
  sessions: [],
  filteredSessions: [],
  selected: null,
  result: null,
  cursor: 0,
  playing: false,
  animating: false,
  complete: false,
  loading: false,
  requestVersion: 0,
  playbackGeneration: 0,
  playbackTimer: null,
  toastTimer: null,
};

const dom = {
  sessionList: document.querySelector("#session-list"),
  sessionCount: document.querySelector("#session-count"),
  connectionState: document.querySelector("#connection-state"),
  candidateName: document.querySelector("#candidate-name"),
  search: document.querySelector("#session-search"),
  scenarioFilter: document.querySelector("#scenario-filter"),
  difficultyFilter: document.querySelector("#difficulty-filter"),
  randomSession: document.querySelector("#random-session"),
  selectedTitle: document.querySelector("#selected-session-title"),
  selectedBadges: document.querySelector("#selected-badges"),
  profileAvatar: document.querySelector("#profile-avatar"),
  profileSummary: document.querySelector("#profile-summary"),
  profileTags: document.querySelector("#profile-tags"),
  profileFacts: document.querySelector("#profile-facts"),
  chatScroll: document.querySelector("#chat-scroll"),
  emptyState: document.querySelector("#empty-state"),
  loadingState: document.querySelector("#loading-state"),
  transcript: document.querySelector("#transcript"),
  playbackBar: document.querySelector("#playback-bar"),
  turnLabel: document.querySelector("#turn-label"),
  turnCounter: document.querySelector("#turn-counter"),
  turnTrack: document.querySelector("#turn-track"),
  speed: document.querySelector("#playback-speed"),
  playButton: document.querySelector("#play-button"),
  playButtonLabel: document.querySelector("#play-button span"),
  stepButton: document.querySelector("#step-button"),
  restartButton: document.querySelector("#restart-button"),
  emptyAutoplay: document.querySelector("#empty-autoplay"),
  emptyStep: document.querySelector("#empty-step"),
  copyTranscript: document.querySelector("#copy-transcript"),
  toast: document.querySelector("#toast"),
};

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const agentAvatarSvg = `
  <svg viewBox="0 0 30 30" aria-hidden="true">
    <path d="M7 8.5h16v10.7a3.8 3.8 0 0 1-3.8 3.8H12a5 5 0 0 1-5-5V8.5Z"></path>
    <path d="M11 8.5V7a4 4 0 0 1 8 0v1.5"></path>
    <path d="m10.5 14 3 2.5 6-5"></path>
  </svg>`;

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = text;
  return element;
}

function scenarioLabel(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function scenarioClass(value) {
  return String(value || "unknown").replaceAll("_", "-");
}

function scenarioAbbreviation(value) {
  const labels = {
    buying: "BY",
    browsing: "BR",
    intent_override: "IO",
    boundary: "BD",
  };
  return labels[value] || "SE";
}

function initialsForProfile(session) {
  const tags = session?.user_profile?.preference_tags || [];
  if (tags.length >= 2) return `${tags[0][0]}${tags[1][0]}`.toUpperCase();
  if (tags.length === 1) return tags[0].slice(0, 2).toUpperCase();
  return "SP";
}

function makeBadge(label, className = "") {
  return createElement("span", `badge ${className}`.trim(), label);
}

function showToast(message, type = "info") {
  window.clearTimeout(state.toastTimer);
  dom.toast.textContent = message;
  dom.toast.className = `toast visible${type === "error" ? " error" : ""}`;
  state.toastTimer = window.setTimeout(() => {
    dom.toast.className = "toast";
  }, 3000);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

function renderTrack() {
  dom.turnTrack.replaceChildren();
  for (let index = 1; index <= 10; index += 1) {
    const segment = createElement("span", "turn-segment");
    segment.dataset.turn = String(index);
    dom.turnTrack.append(segment);
  }
}

function updateProgress(turn = 0, terminal = false, hit = false) {
  const segments = [...dom.turnTrack.children];
  segments.forEach((segment, index) => {
    const segmentTurn = index + 1;
    segment.className = "turn-segment";
    if (segmentTurn < turn || (terminal && segmentTurn <= turn)) {
      segment.classList.add("complete");
    } else if (segmentTurn === turn) {
      segment.classList.add("current");
    }
    if (terminal && hit && segmentTurn === turn) segment.classList.add("hit");
  });
  dom.turnCounter.textContent = `${turn} / 10`;
  if (terminal) {
    dom.turnLabel.textContent = hit ? "Target product found" : "Turn limit reached";
  } else if (turn > 0) {
    dom.turnLabel.textContent = `Playing turn ${turn}`;
  } else {
    dom.turnLabel.textContent = "Ready to play";
  }
}

function renderSessionList() {
  dom.sessionList.replaceChildren();
  if (!state.filteredSessions.length) {
    dom.sessionList.append(
      createElement("div", "no-sessions", "No sessions match those filters. Try a broader search."),
    );
    dom.sessionCount.textContent = "0 sessions";
    return;
  }

  const fragment = document.createDocumentFragment();
  const selectedIsVisible = state.filteredSessions.some(
    (session) => session.sample_id === state.selected?.sample_id,
  );
  state.filteredSessions.forEach((session, index) => {
    const option = createElement("button", "session-option");
    option.type = "button";
    option.setAttribute("role", "option");
    option.dataset.sessionId = session.sample_id;
    const selected = state.selected?.sample_id === session.sample_id;
    option.classList.toggle("selected", selected);
    option.setAttribute("aria-selected", String(selected));
    option.tabIndex = selected || (!selectedIsVisible && index === 0) ? 0 : -1;
    option.setAttribute(
      "aria-label",
      `${session.sample_id}, ${scenarioLabel(session.scenario_type)}, ${session.difficulty_bucket} difficulty`,
    );

    option.append(createElement("span", "session-icon", scenarioAbbreviation(session.scenario_type)));
    const copy = createElement("span", "session-copy");
    copy.append(createElement("strong", "", session.sample_id));
    const tags = session.user_profile.preference_tags.slice(0, 3).join(" · ");
    copy.append(createElement("span", "", tags || scenarioLabel(session.scenario_type)));
    option.append(copy);
    const difficulty = createElement("span", `difficulty-mark ${session.difficulty_bucket}`);
    difficulty.setAttribute("aria-hidden", "true");
    option.append(difficulty);
    option.addEventListener("click", () => selectSession(session, { focusList: true }));
    option.addEventListener("keydown", (event) => navigateSessionList(event, index));
    fragment.append(option);
  });
  dom.sessionList.append(fragment);
  const suffix = state.filteredSessions.length === 1 ? "session" : "sessions";
  dom.sessionCount.textContent = `${state.filteredSessions.length} ${suffix}`;
}

function navigateSessionList(event, currentIndex) {
  const lastIndex = state.filteredSessions.length - 1;
  let nextIndex = null;
  if (event.key === "ArrowDown" || event.key === "ArrowRight") {
    nextIndex = Math.min(lastIndex, currentIndex + 1);
  } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
    nextIndex = Math.max(0, currentIndex - 1);
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = lastIndex;
  }
  if (nextIndex === null || nextIndex < 0 || nextIndex === currentIndex) return;
  event.preventDefault();
  selectSession(state.filteredSessions[nextIndex], { focusList: true });
}

function filterSessions() {
  const query = dom.search.value.trim().toLowerCase();
  const scenario = dom.scenarioFilter.value;
  const difficulty = dom.difficultyFilter.value;
  state.filteredSessions = state.sessions.filter((session) => {
    if (scenario !== "all" && session.scenario_type !== scenario) return false;
    if (difficulty !== "all" && session.difficulty_bucket !== difficulty) return false;
    if (!query) return true;
    const haystack = [
      session.sample_id,
      session.scenario_type,
      session.difficulty_bucket,
      session.user_profile.summary,
      ...session.user_profile.preference_tags,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
  renderSessionList();
  updateControls();
}

function factNode(label, value) {
  const wrapper = createElement("div", "profile-fact");
  wrapper.append(createElement("dt", "", label));
  wrapper.append(createElement("dd", "", value));
  return wrapper;
}

function renderSelectedSession() {
  const session = state.selected;
  if (!session) return;
  dom.selectedTitle.textContent = session.sample_id;
  dom.selectedBadges.replaceChildren(
    makeBadge(scenarioLabel(session.scenario_type), scenarioClass(session.scenario_type)),
    makeBadge(session.difficulty_bucket, "difficulty"),
  );

  dom.profileAvatar.textContent = initialsForProfile(session);
  dom.profileSummary.textContent = session.user_profile.summary;
  dom.profileTags.replaceChildren();
  session.user_profile.preference_tags.slice(0, 5).forEach((tag) => {
    dom.profileTags.append(createElement("span", "tag", tag));
  });

  const average = session.user_profile.average_prior_rating;
  dom.profileFacts.replaceChildren(
    factNode("Purchase history", session.user_profile.purchase_frequency),
    factNode("Rating style", session.user_profile.rating_style),
    factNode("Prior average", typeof average === "number" ? `${average.toFixed(1)} / 5` : "Unknown"),
  );
}

function clearPlaybackTimer() {
  window.clearTimeout(state.playbackTimer);
  state.playbackTimer = null;
}

function resetViewer() {
  clearPlaybackTimer();
  state.playbackGeneration += 1;
  state.result = null;
  state.cursor = 0;
  state.playing = false;
  state.animating = false;
  state.complete = false;
  state.loading = false;
  dom.transcript.replaceChildren();
  dom.emptyState.hidden = false;
  dom.loadingState.hidden = true;
  dom.playbackBar.hidden = true;
  dom.copyTranscript.disabled = true;
  updateProgress(0);
  updateControls();
}

function selectSession(session, { focusList = false } = {}) {
  if (!session) return;
  state.requestVersion += 1;
  state.selected = session;
  resetViewer();
  renderSelectedSession();
  renderSessionList();
  const active = dom.sessionList.querySelector(`[data-session-id="${CSS.escape(session.sample_id)}"]`);
  active?.scrollIntoView({ block: "nearest", inline: "nearest" });
  if (focusList) requestAnimationFrame(() => active?.focus());
}

function pickRandomSession() {
  const pool = state.filteredSessions;
  if (!pool.length) return;
  let session = pool[Math.floor(Math.random() * pool.length)];
  if (pool.length > 1 && session.sample_id === state.selected?.sample_id) {
    session = pool[(pool.indexOf(session) + 1) % pool.length];
  }
  selectSession(session);
}

function setPlayButton(mode) {
  const path = dom.playButton.querySelector("path");
  if (mode === "pause") {
    path.setAttribute("d", "M9 7v10M15 7v10");
    path.style.fill = "none";
    path.style.stroke = "currentColor";
    dom.playButtonLabel.textContent = "Pause";
  } else {
    path.setAttribute("d", "m9 7 8 5-8 5V7Z");
    path.style.fill = "currentColor";
    path.style.stroke = "none";
    dom.playButtonLabel.textContent = mode === "replay" ? "Replay" : "Auto play";
  }
}

function updateControls() {
  const hasSelection = Boolean(state.selected);
  dom.emptyAutoplay.disabled = !hasSelection || state.loading;
  dom.emptyStep.disabled = !hasSelection || state.loading;
  dom.randomSession.disabled = state.filteredSessions.length === 0;

  if (dom.playbackBar.hidden) return;
  dom.stepButton.disabled = state.loading || state.animating || state.complete;
  dom.restartButton.disabled = state.loading || state.animating;
  dom.playButton.disabled = state.loading;
  setPlayButton(state.complete ? "replay" : state.playing ? "pause" : "play");
}

function transcriptDivider() {
  return createElement("div", "transcript-divider", "Simulated conversation");
}

function userMessage(turn) {
  const row = createElement("article", "message-row user");
  row.dataset.turn = String(turn.turn);
  row.append(createElement("div", "message-avatar", initialsForProfile(state.selected)));
  const stack = createElement("div", "message-stack");
  stack.append(createElement("div", "message-meta", `Customer · Turn ${turn.turn}`));
  const bubble = createElement("div", "message-bubble");
  bubble.append(createElement("p", "", turn.user.message));
  stack.append(bubble);
  row.append(stack);
  return row;
}

function userTypingMessage(turn) {
  const row = createElement("article", "message-row user customer-typing-row");
  row.dataset.typing = "true";
  row.append(createElement("div", "message-avatar", initialsForProfile(state.selected)));
  const stack = createElement("div", "message-stack");
  stack.append(createElement("div", "message-meta", `Customer · Typing turn ${turn.turn}`));
  const bubble = createElement("div", "customer-typing-bubble");
  bubble.setAttribute("role", "status");
  bubble.setAttribute("aria-label", `The customer is typing turn ${turn.turn}`);
  const dots = createElement("span", "customer-typing-dots");
  dots.setAttribute("aria-hidden", "true");
  dots.append(createElement("i"), createElement("i"), createElement("i"));
  bubble.append(dots);
  stack.append(bubble);
  row.append(stack);
  return row;
}

function typingMessage(turn) {
  const row = createElement("article", "message-row assistant typing-row");
  row.dataset.typing = "true";
  const avatar = createElement("div", "message-avatar");
  avatar.innerHTML = agentAvatarSvg;
  row.append(avatar);
  const stack = createElement("div", "message-stack");
  stack.append(createElement("div", "message-meta", "Shopping agent · Thinking"));
  const bubble = createElement("div", "typing-bubble");
  bubble.setAttribute("role", "status");
  bubble.setAttribute("aria-label", "The shopping agent is thinking");

  const spinner = createElement("span", "thinking-spinner");
  spinner.setAttribute("aria-hidden", "true");
  const copy = createElement("span", "thinking-copy");
  copy.append(createElement("strong", "", "Agent is thinking"));
  const isOverride = turn.user.message.toLowerCase().includes("actually");
  copy.append(
    createElement(
      "span",
      "",
      isOverride
        ? "Updating the intent and ranking again…"
        : turn.turn === 1
          ? "Reading the request and searching 50,000 products…"
          : "Applying the new details and reranking matches…",
    ),
  );
  const dots = createElement("span", "thinking-dots");
  dots.setAttribute("aria-hidden", "true");
  dots.append(createElement("i"), createElement("i"), createElement("i"));
  bubble.append(spinner, copy, dots);
  stack.append(bubble);
  row.append(stack);
  return row;
}

function productGlyph(product) {
  const text = `${product.category || ""} ${product.title || ""}`.toLowerCase();
  if (/boot|hiking/.test(text)) return "🥾";
  if (/shoe|sneaker|trainer/.test(text)) return "👟";
  if (/dress|gown/.test(text)) return "👗";
  if (/shirt|tee|top|blouse/.test(text)) return "👕";
  if (/coat|jacket|hoodie/.test(text)) return "🧥";
  if (/ring|earring|necklace|jewelry|jewellery/.test(text)) return "💎";
  if (/watch/.test(text)) return "⌚";
  if (/bag|purse|handbag/.test(text)) return "👜";
  if (/hat|cap|beanie/.test(text)) return "🧢";
  if (/sock/.test(text)) return "🧦";
  return "✦";
}

function formatPrice(value) {
  const number = typeof value === "number" ? value : Number.parseFloat(value);
  if (!Number.isFinite(number)) return "Price n/a";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: number % 1 === 0 ? 0 : 2,
  }).format(number);
}

function formatRating(product) {
  const rating = Number(product.average_rating);
  if (!Number.isFinite(rating)) return "No rating";
  const count = Number(product.rating_number);
  const countText = Number.isFinite(count)
    ? ` · ${new Intl.NumberFormat("en-US", { notation: "compact" }).format(count)}`
    : "";
  return `★ ${rating.toFixed(1)}${countText}`;
}

function formatCompactNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "—");
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(
    number,
  );
}

function productCard(product) {
  const card = createElement("article", `product-card${product.is_target ? " is-target" : ""}`);
  const art = createElement("div", "product-art");
  art.append(createElement("span", "product-glyph", productGlyph(product)));
  art.append(createElement("span", "rank-pill", `#${product.rank}`));
  if (product.is_target) art.append(createElement("span", "target-pill", "Target found"));
  card.append(art);

  const copy = createElement("div", "product-copy");
  copy.append(createElement("span", "product-store", product.store || product.category || "Product"));
  copy.append(createElement("p", "product-title", product.title));
  const meta = createElement("div", "product-meta");
  meta.append(createElement("span", "product-price", formatPrice(product.price)));
  const rating = createElement("span", "rating");
  const ratingText = formatRating(product);
  if (ratingText.startsWith("★")) {
    const star = createElement("strong", "", "★");
    rating.append(star, document.createTextNode(ratingText.slice(1)));
  } else {
    rating.textContent = ratingText;
  }
  meta.append(rating);
  copy.append(meta);
  card.append(copy);
  return card;
}

function traceRow(trace) {
  if (trace?.route) {
    const panel = createElement("section", "decision-trace");
    panel.setAttribute("aria-label", "Candidate filtering");

    const heading = createElement("div", "decision-trace-heading");
    heading.append(createElement("span", "decision-trace-title", "Candidate filtering"));
    const exceptionalRoute = trace.phase || (trace.route !== "exact-inverse" ? trace.route : null);
    if (exceptionalRoute) {
      heading.append(
        createElement(
          "span",
          `route-chip ${exceptionalRoute}`,
          exceptionalRoute === "intent-override"
            ? "Intent override"
            : "NLP recovery",
        ),
      );
    }
    panel.append(heading);

    const funnel = createElement("div", "candidate-funnel");
    funnel.append(
      createElement("strong", "", formatCompactNumber(trace.previous_candidates)),
      createElement("span", "funnel-arrow", "→"),
      createElement("strong", "", formatCompactNumber(trace.active_candidates)),
      createElement("span", "", "candidates"),
      createElement("span", "funnel-arrow", "→"),
      createElement("strong", "", `top ${trace.k ?? 0}`),
      createElement("span", "", "shown"),
    );
    panel.append(funnel);

    if (Array.isArray(trace.evidence) && trace.evidence.length) {
      const evidence = createElement("div", "evidence-row");
      evidence.append(createElement("span", "evidence-label", "Matched evidence"));
      trace.evidence.forEach((item) => {
        const chip = createElement(
          "span",
          `evidence-chip${item.kind === "negative" ? " negative" : ""}`,
          item.text,
        );
        chip.title = `${item.slot || "feature"} · ${item.kind || "active"}`;
        evidence.append(chip);
      });
      panel.append(evidence);
    }
    return panel;
  }

  const values = [];
  if (trace?.intent) values.push(trace.intent);
  if (trace?.mode) values.push(`mode:${trace.mode}`);
  if (trace?.policy) values.push(`${trace.policy}${trace.k ? ` · K=${trace.k}` : ""}`);
  if (!values.length) return null;
  const row = createElement("div", "trace-row");
  values.forEach((value) => row.append(createElement("span", "trace-chip", value)));
  return row;
}

function assistantMessage(turn) {
  const row = createElement("article", "message-row assistant");
  row.dataset.turn = String(turn.turn);
  const avatar = createElement("div", "message-avatar");
  avatar.innerHTML = agentAvatarSvg;
  row.append(avatar);

  const stack = createElement("div", "message-stack");
  stack.append(createElement("div", "message-meta", `Shopping agent · Turn ${turn.turn}`));
  const bubble = createElement("div", "message-bubble");
  bubble.append(
    createElement(
      "p",
      "",
      turn.assistant.message || "No conversational message was returned for this turn.",
    ),
  );
  stack.append(bubble);

  const details = createElement("div", "assistant-details");
  if (turn.assistant.ask_attribute) {
    details.append(
      createElement(
        "div",
        "ask-chip",
        `Asking about: ${scenarioLabel(turn.assistant.ask_attribute).toLowerCase()}`,
      ),
    );
  }
  const trace = traceRow(turn.assistant.trace);
  if (trace) details.append(trace);

  if (turn.assistant.recommendations.length) {
    const label = createElement("div", "recommendation-label");
    label.append(
      createElement("span", "", "Recommended products"),
      createElement(
        "span",
        "",
        `${turn.assistant.recommendations.length} result${turn.assistant.recommendations.length === 1 ? "" : "s"}`,
      ),
    );
    details.append(label);
    const scroll = createElement("div", "recommendation-scroll");
    turn.assistant.recommendations.forEach((product) => scroll.append(productCard(product)));
    details.append(scroll);
  } else {
    details.append(createElement("div", "no-recommendations", "No valid products returned this turn."));
  }

  if (turn.assistant.warning) {
    details.append(createElement("div", "agent-warning", turn.assistant.warning));
  }
  stack.append(details);
  row.append(stack);
  return row;
}

function outcomeCard(outcome) {
  const card = createElement("section", `outcome-card${outcome.hit ? "" : " miss"}`);
  const icon = createElement("div", "outcome-icon");
  icon.innerHTML = outcome.hit
    ? `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4.5 4.5L19 7"></path></svg>`
    : `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"></circle><path d="M12 8v5M12 16h.01"></path></svg>`;
  card.append(icon);

  const copy = createElement("div", "outcome-copy");
  copy.append(
    createElement("p", "eyebrow", outcome.hit ? "Successful match" : "Target revealed"),
  );
  copy.append(createElement("h4", "", outcome.target.title));
  copy.append(
    createElement(
      "p",
      "",
      outcome.hit
        ? `${outcome.target.parent_asin} matched at rank ${outcome.best_rank}.`
        : `${outcome.target.parent_asin} was not present in a scored list by turn 10.`,
    ),
  );
  copy.append(
    createElement(
      "p",
      "verdict-note",
      "Evaluator verdict added after the Agent response; the hidden target was never sent to the Agent.",
    ),
  );
  card.append(copy);

  const stats = createElement("div", "outcome-stats");
  const statValues = [
    [String(outcome.turns), "Turns"],
    [outcome.hit ? `#${outcome.best_rank}` : "—", "Best rank"],
    [String(outcome.unique_products), "Products"],
  ];
  statValues.forEach(([value, label]) => {
    const stat = createElement("div", "outcome-stat");
    stat.append(createElement("strong", "", value), createElement("span", "", label));
    stats.append(stat);
  });
  card.append(stats);
  return card;
}

function scrollToLatest(behavior = "smooth") {
  requestAnimationFrame(() => {
    dom.chatScroll.scrollTo({ top: dom.chatScroll.scrollHeight, behavior });
  });
}

function wait(milliseconds, generation) {
  return new Promise((resolve) => {
    window.setTimeout(() => resolve(generation === state.playbackGeneration), milliseconds);
  });
}

function playbackDelay() {
  return reducedMotion ? 20 : Number(dom.speed.value || 900);
}

function customerTypingDelay(message) {
  if (reducedMotion) return 280;
  const speedScale = Math.max(0.4, Math.min(1.7, playbackDelay() / 900));
  const naturalDelay = Math.max(650, Math.min(1250, 480 + String(message).length * 9));
  return Math.max(320, Math.min(1900, Math.round(naturalDelay * speedScale)));
}

function readingPause() {
  return reducedMotion ? 100 : Math.max(120, Math.min(420, Math.round(playbackDelay() * 0.25)));
}

function replyPause() {
  return reducedMotion ? 100 : Math.max(100, Math.min(360, Math.round(playbackDelay() * 0.22)));
}

function scheduleNextTurn(delay = Math.round(playbackDelay() * 0.72)) {
  clearPlaybackTimer();
  state.playbackTimer = window.setTimeout(() => {
    if (state.playing && !state.complete) revealNextTurn();
  }, reducedMotion ? 20 : delay);
}

async function revealNextTurn() {
  if (!state.result || state.animating || state.complete) return;
  if (state.cursor >= state.result.transcript.length) {
    finalizePlayback();
    return;
  }

  state.animating = true;
  updateControls();
  const generation = state.playbackGeneration;
  const turn = state.result.transcript[state.cursor];
  updateProgress(turn.turn);
  const customerTyping = userTypingMessage(turn);
  dom.transcript.append(customerTyping);
  scrollToLatest();

  if (!(await wait(customerTypingDelay(turn.user.message), generation))) return;
  customerTyping.replaceWith(userMessage(turn));
  scrollToLatest();

  if (!(await wait(readingPause(), generation))) return;
  const typing = typingMessage(turn);
  dom.transcript.append(typing);
  scrollToLatest();

  const thinkingPause = reducedMotion
    ? 450
    : Math.max(620, Math.min(1400, Math.round(playbackDelay() * 0.92)));
  if (!(await wait(thinkingPause, generation))) return;
  typing.remove();
  if (!(await wait(replyPause(), generation))) return;
  dom.transcript.append(assistantMessage(turn));
  state.cursor += 1;
  state.animating = false;
  scrollToLatest();

  if (turn.hit || state.cursor >= state.result.transcript.length) {
    finalizePlayback();
  } else if (state.playing) {
    scheduleNextTurn();
  }
  updateControls();
}

function finalizePlayback() {
  if (state.complete || !state.result) return;
  clearPlaybackTimer();
  state.complete = true;
  state.playing = false;
  state.animating = false;
  dom.transcript.append(outcomeCard(state.result.outcome));
  updateProgress(
    state.result.outcome.turns,
    true,
    state.result.outcome.hit,
  );
  dom.copyTranscript.disabled = false;
  updateControls();
  scrollToLatest();
}

function prepareTranscript() {
  state.playbackGeneration += 1;
  clearPlaybackTimer();
  state.cursor = 0;
  state.playing = false;
  state.animating = false;
  state.complete = false;
  dom.transcript.replaceChildren(transcriptDivider());
  dom.emptyState.hidden = true;
  dom.loadingState.hidden = true;
  dom.playbackBar.hidden = false;
  dom.copyTranscript.disabled = true;
  updateProgress(0);
}

async function startSimulation(autoplay) {
  if (!state.selected || state.loading) return;
  const selectedId = state.selected.sample_id;
  const requestVersion = ++state.requestVersion;
  clearPlaybackTimer();
  state.playbackGeneration += 1;
  state.loading = true;
  state.playing = false;
  state.complete = false;
  dom.emptyState.hidden = true;
  dom.loadingState.hidden = false;
  dom.transcript.replaceChildren();
  dom.playbackBar.hidden = true;
  updateControls();

  try {
    const result = await fetchJson("/api/simulate", {
      method: "POST",
      body: JSON.stringify({ sample_id: selectedId }),
    });
    if (requestVersion !== state.requestVersion || selectedId !== state.selected?.sample_id) return;
    state.result = result;
    state.loading = false;
    prepareTranscript();
    state.playing = autoplay;
    updateControls();
    await revealNextTurn();
  } catch (error) {
    if (requestVersion !== state.requestVersion) return;
    state.loading = false;
    dom.loadingState.hidden = true;
    dom.emptyState.hidden = false;
    updateControls();
    showToast(error.message || "Could not run this simulation.", "error");
  }
}

function togglePlayback() {
  if (!state.result) {
    startSimulation(true);
    return;
  }
  if (state.complete) {
    replaySimulation(true);
    return;
  }
  state.playing = !state.playing;
  if (state.playing && !state.animating) scheduleNextTurn(20);
  if (!state.playing) clearPlaybackTimer();
  updateControls();
}

function stepPlayback() {
  if (!state.result) {
    startSimulation(false);
    return;
  }
  state.playing = false;
  clearPlaybackTimer();
  revealNextTurn();
  updateControls();
}

function replaySimulation(autoplay = true) {
  if (!state.result) {
    startSimulation(autoplay);
    return;
  }
  prepareTranscript();
  state.playing = autoplay;
  updateControls();
  revealNextTurn();
}

function transcriptText() {
  if (!state.result) return "";
  const lines = [
    `Session: ${state.result.session.sample_id}`,
    `Scenario: ${scenarioLabel(state.result.session.scenario_type)}`,
    `Candidate: ${state.result.candidate}`,
    "",
  ];
  state.result.transcript.forEach((turn) => {
    lines.push(`Turn ${turn.turn} — Customer: ${turn.user.message}`);
    lines.push(`Turn ${turn.turn} — Agent: ${turn.assistant.message || "(no message)"}`);
    if (turn.assistant.ask_attribute) lines.push(`Asked attribute: ${turn.assistant.ask_attribute}`);
    if (turn.assistant.recommendations.length) {
      lines.push(
        `Recommendations: ${turn.assistant.recommendations
          .map((product) => `${product.rank}. ${product.title} (${product.parent_asin})`)
          .join(" | ")}`,
      );
    }
    if (turn.assistant.trace?.route) {
      lines.push(
        `Candidate filtering: ${turn.assistant.trace.previous_candidates} -> ${turn.assistant.trace.active_candidates}; showing top ${turn.assistant.trace.k}.`,
      );
    }
    lines.push("");
  });
  const outcome = state.result.outcome;
  lines.push(
    outcome.hit
      ? `Outcome: Target found on turn ${outcome.first_hit_turn} at rank ${outcome.best_rank}.`
      : "Outcome: Target not found within 10 turns.",
  );
  lines.push(`Target: ${outcome.target.title} (${outcome.target.parent_asin})`);
  return lines.join("\n");
}

function sessionIdFromHash() {
  const raw = window.location.hash.replace(/^#/, "");
  try {
    return decodeURIComponent(raw);
  } catch {
    return "";
  }
}

async function copyTranscript() {
  const text = transcriptText();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    showToast("Transcript copied to clipboard.");
  } catch {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.append(textArea);
    textArea.select();
    document.execCommand("copy");
    textArea.remove();
    showToast("Transcript copied to clipboard.");
  }
}

function bindEvents() {
  dom.search.addEventListener("input", filterSessions);
  dom.scenarioFilter.addEventListener("change", filterSessions);
  dom.difficultyFilter.addEventListener("change", filterSessions);
  dom.randomSession.addEventListener("click", pickRandomSession);
  dom.emptyAutoplay.addEventListener("click", () => startSimulation(true));
  dom.emptyStep.addEventListener("click", () => startSimulation(false));
  dom.playButton.addEventListener("click", togglePlayback);
  dom.stepButton.addEventListener("click", stepPlayback);
  dom.restartButton.addEventListener("click", () => replaySimulation(true));
  dom.copyTranscript.addEventListener("click", copyTranscript);
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      dom.search.focus();
    }
    if (event.key === " " && event.target === document.body && !state.loading) {
      event.preventDefault();
      togglePlayback();
    }
  });
}

async function initialize() {
  renderTrack();
  bindEvents();
  try {
    const payload = await fetchJson("/api/sessions");
    state.sessions = payload.sessions || [];
    state.filteredSessions = [...state.sessions];
    dom.candidateName.textContent = payload.candidate || "Unknown candidate";
    dom.connectionState.className = "connection-state online";
    dom.connectionState.lastChild.textContent = " Online";
    renderSessionList();
    const hashId = sessionIdFromHash();
    const initial = state.sessions.find((session) => session.sample_id === hashId) || state.sessions[0];
    if (initial) selectSession(initial);
  } catch (error) {
    dom.connectionState.className = "connection-state error";
    dom.connectionState.lastChild.textContent = " Offline";
    dom.sessionCount.textContent = "Could not load sessions";
    dom.sessionList.replaceChildren(
      createElement(
        "div",
        "no-sessions",
        "The local frontend server is unavailable. Start it with `make frontend` and refresh.",
      ),
    );
    showToast(error.message || "Could not connect to the local server.", "error");
  }
}

initialize();
