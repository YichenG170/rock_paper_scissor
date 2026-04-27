let sessionId = null;
let messageIndex = 0;
let lastState = {};
let selectedItemId = null;

const el = (id) => document.getElementById(id);

const labels = {
  rock: "石头",
  scissors: "剪刀",
  paper: "布",
  none: "跳过",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function api(path, body) {
  return fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  }).then(async (res) => {
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error(data.error || "请求失败");
    return data;
  });
}

function action(payload) {
  return api("/api/action", {session: sessionId, payload});
}

function setPhase(text) {
  el("phase").textContent = text;
}

function percent(rate) {
  return `${Math.round((rate || 0) * 100)}%`;
}

function formatItem(item) {
  const rarity = item.rarity ? ` / ${item.rarity}` : "";
  return `<div class="detailItem"><b>${escapeHtml(item.name || item.id || "未知道具")}</b><small>${escapeHtml((item.description || "") + rarity)}</small></div>`;
}

function formatTalent(talent) {
  return `<div class="detailItem"><b>${escapeHtml(talent.name || talent.id || "未知天赋")}</b><small>${escapeHtml(talent.description || "")}</small></div>`;
}

function renderDetails(msg) {
  const ownedItems = msg.owned_items || msg.items || lastState.owned_items || lastState.items || [];
  const myTalents = msg.owned_talents || msg.your_talents || lastState.owned_talents || lastState.your_talents || [];
  const opponentTalents = msg.opponent_talents || lastState.opponent_talents || [];

  el("selfDetail").innerHTML = `
    <div class="detailGrid">
      <span>血量</span><b>${escapeHtml(msg.your_health ?? msg.health ?? lastState.your_health ?? lastState.health ?? "-")}</b>
      <span>金币</span><b>${escapeHtml(msg.your_gold ?? msg.gold ?? lastState.your_gold ?? lastState.gold ?? "-")}</b>
      <span>攻击</span><b>${escapeHtml(msg.your_attack ?? msg.attack ?? lastState.your_attack ?? lastState.attack ?? "-")}</b>
      <span>利息</span><b>${percent(msg.your_interest_rate ?? msg.interest_rate ?? lastState.your_interest_rate ?? lastState.interest_rate ?? 0)}</b>
      <span>连胜</span><b>${escapeHtml(msg.your_win_streak ?? msg.win_streak ?? lastState.your_win_streak ?? lastState.win_streak ?? 0)}</b>
      <span>连败</span><b>${escapeHtml(msg.your_lose_streak ?? msg.lose_streak ?? lastState.your_lose_streak ?? lastState.lose_streak ?? 0)}</b>
    </div>
    <h3>道具</h3>
    ${ownedItems.length ? ownedItems.map(formatItem).join("") : "<small>暂无道具</small>"}
    <h3>天赋</h3>
    ${myTalents.length ? myTalents.map(formatTalent).join("") : "<small>暂无天赋</small>"}
  `;

  el("opponentDetail").innerHTML = opponentTalents.length
    ? opponentTalents.map(formatTalent).join("")
    : "<small>暂无可见天赋</small>";
}

function updateStats(msg) {
  lastState = {...lastState, ...msg};
  const stats = [
    ["血量", msg.your_health ?? msg.health],
    ["金币", msg.your_gold ?? msg.gold],
    ["攻击", msg.your_attack ?? msg.attack],
    ["容量", msg.your_bag_size ?? msg.bag_size],
    ["利息", percent(msg.your_interest_rate ?? msg.interest_rate ?? 0)],
    ["连胜/败", `${msg.your_win_streak ?? msg.win_streak ?? 0}/${msg.your_lose_streak ?? msg.lose_streak ?? 0}`],
  ].filter((row) => row[1] !== undefined);
  el("stats").innerHTML = stats.map(([k, v]) => `<div class="stat"><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`).join("");
  renderHealth(msg.health_overview || lastState.health_overview || []);
  if (msg.bag) renderBag(msg.bag);
  renderDetails(msg);
}

function renderHealth(list) {
  el("healthBoard").innerHTML = list.length
    ? list.map((p) => `<div class="healthItem"><span>${escapeHtml(p.name)}</span><b>${escapeHtml(p.health)}${p.is_eliminated ? " 已淘汰" : ""}</b></div>`).join("")
    : `<div class="healthItem"><span>暂无数据</span><b>-</b></div>`;
}

function renderBag(bag) {
  el("bag").innerHTML = ["rock", "scissors", "paper"].map((k) =>
    `<div class="bagItem">${labels[k]} <b>${escapeHtml(bag[k] || 0)}</b></div>`
  ).join("");
}

function addLog(title, lines = []) {
  const node = document.createElement("div");
  node.className = "logEntry";
  node.innerHTML = `<b>${escapeHtml(title)}</b>${lines.map((line) => `<div><small>${escapeHtml(line)}</small></div>`).join("")}`;
  el("log").prepend(node);
}

function renderChoose(msg) {
  updateStats(msg);
  selectedItemId = null;
  setPhase(`对战 ${msg.opponent}，第 ${msg.round_no}/${msg.max_rounds} 小局`);
  renderBag(msg.bag || {});
  const choices = ["rock", "scissors", "paper"].map((choice) => {
    const count = (msg.bag || {})[choice] || 0;
    return `<button class="choice ${choice}" ${count <= 0 ? "disabled" : ""} data-choice="${choice}">
      <strong>${labels[choice]}</strong><span>剩余 ${count}</span>
    </button>`;
  }).join("");
  const items = (msg.items || []).map((item) =>
    `<button class="itemButton" data-item="${escapeHtml(item.id)}"><b>${escapeHtml(item.name)}</b><br><small>${escapeHtml(item.description || "")}</small></button>`
  ).join("");
  el("actionArea").innerHTML = `
    <div class="toolbar"><button id="skipBtn">跳过</button></div>
    <h2>选择出拳</h2>
    <div class="choices">${choices}</div>
    <h2>本局道具</h2>
    <div class="items">${items || "<small>没有可用道具</small>"}</div>
  `;
  document.querySelectorAll("[data-choice]").forEach((btn) => {
    btn.onclick = () => action({choice: btn.dataset.choice, use_item: selectedItemId}).then(() => {
      setPhase("已提交，等待对手");
      el("actionArea").innerHTML = "";
    });
  });
  document.querySelectorAll("[data-item]").forEach((btn) => {
    btn.onclick = () => {
      selectedItemId = btn.dataset.item;
      document.querySelectorAll("[data-item]").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      addLog("已选择道具", [btn.innerText.split("\n")[0]]);
    };
  });
  el("skipBtn").onclick = () => action({choice: "none", use_item: selectedItemId});
}

function renderShop(msg) {
  updateStats(msg);
  setPhase(`商店阶段，刷新费用 ${msg.refresh_cost} 金币`);
  renderBag(msg.bag || lastState.bag || {});
  el("actionArea").innerHTML = `
    <div class="toolbar">
      <button id="refreshBtn">刷新</button>
      <button id="exitShopBtn">退出商店</button>
    </div>
    <div class="offers">${(msg.offers || []).map((offer, index) => `
      <button class="offer" data-slot="${index}">
        <span class="offerHeader"><b>${escapeHtml(offer.name)}</b><strong>${escapeHtml(offer.cost)} 金</strong></span>
        <small>${offer.kind === "talent" ? "天赋" : escapeHtml(offer.rarity || "道具")}</small>
        <span>${escapeHtml(offer.description || "")}</span>
      </button>`).join("")}</div>
  `;
  document.querySelectorAll("[data-slot]").forEach((btn) => {
    btn.onclick = () => action({choice: `slot_${btn.dataset.slot}`});
  });
  el("refreshBtn").onclick = () => action({choice: "refresh"});
  el("exitShopBtn").onclick = () => action({choice: "exit"}).then(() => {
    setPhase("已离开商店，等待其他玩家");
    el("actionArea").innerHTML = "";
  });
}

function handleRoundResult(msg) {
  updateStats(msg);
  const itemYou = msg.item_used_you || "无";
  const itemOpponent = msg.item_used_opponent || "无";
  const events = msg.round_summary && msg.round_summary.length ? msg.round_summary : ["无额外触发"];
  addLog(`第 ${msg.round_no}/${msg.max_rounds} 小局`, [
    `出拳：你 ${labels[msg.your_choice] || msg.your_choice || "无"} / 对手 ${labels[msg.opponent_choice] || msg.opponent_choice || "无"}`,
    msg.round_winner ? `胜者：${msg.round_winner}` : "结果：平局/无效",
    `比分：${msg.score_you}:${msg.score_opponent}`,
    `道具：你 ${itemYou} / 对手 ${itemOpponent}`,
    "触发：",
    ...events,
  ]);
}

function handleMessage(msg) {
  if (msg.type === "choose_rps") renderChoose(msg);
  else if (msg.type === "shop_menu" || msg.type === "shop_refresh") renderShop(msg);
  else if (msg.type === "round_result") handleRoundResult(msg);
  else if (msg.type === "match_result") {
    updateStats(msg);
    const events = msg.round_summary && msg.round_summary.length ? msg.round_summary : [];
    addLog("本场结果", [`结果：${msg.result}`, `比分：${msg.score_you}:${msg.score_opponent}`, ...events]);
    setPhase("等待进入商店或下一轮");
  } else if (msg.type === "state_update") {
    updateStats(msg);
    const income = msg.income ? [`收入：基础 ${msg.income.base}，连胜/败 ${msg.income.streak}，利息 ${msg.income.interest}，合计 ${msg.income.total}`] : [];
    addLog(`状态同步：${msg.phase || "unknown"}`, income);
  } else if (msg.type === "match_start") {
    addLog("对战开始", [`${msg.p1} VS ${msg.p2}`]);
  } else if (msg.type === "observer_round" || msg.type === "match_end") {
    addLog("观战消息", [JSON.stringify(msg)]);
  } else if (msg.type === "disconnect") {
    setPhase("连接已断开");
    addLog("连接断开", [msg.error || ""]);
  }
}

async function poll() {
  if (!sessionId) return;
  try {
    const res = await fetch(`/api/messages?session=${encodeURIComponent(sessionId)}&after=${messageIndex}`);
    const data = await res.json();
    if (data.ok) {
      messageIndex = data.index;
      data.messages.forEach((entry) => handleMessage(entry.data));
    }
  } catch (err) {
    addLog("轮询失败", [err.message]);
  } finally {
    setTimeout(poll, 700);
  }
}

el("connectForm").onsubmit = async (event) => {
  event.preventDefault();
  el("connectError").textContent = "";
  try {
    const data = await api("/api/connect", {
      name: el("nameInput").value,
      host: el("hostInput").value,
      maxPlayers: el("maxPlayersInput").value,
      createServer: el("createServerInput").checked,
    });
    sessionId = data.sessionId;
    el("connectView").classList.add("hidden");
    el("gameView").classList.remove("hidden");
    setPhase("已连接，等待玩家到齐");
    poll();
  } catch (err) {
    el("connectError").textContent = err.message;
  }
};
