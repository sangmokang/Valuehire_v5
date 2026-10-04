// Valuehire AC-8/D9 — 자동화 조작 중 빨간 띠 오버레이.
//
// 신호 프로토콜: 자동화(파이썬)가 CDP 로 페이지에
//   window.dispatchEvent(new CustomEvent("valuehire:automation",
//     { detail: { active: true|false, task: "..." } }))
// 를 dispatch 하면, 이 content script 가 수신해 배너를 표시/제거한다.
(() => {
  "use strict";

  const BANNER_ID = "valuehire-automation-banner";

  // 문서 준비(DOMContentLoaded) 전에 표시 신호가 오면 부착을 예약하는데,
  // 그 사이 제거 신호가 오면 예약을 취소해야 한다(최신 신호 우선).
  // 취소 없이는 제거 후 문서 준비 시 배너가 다시 나타나는 경쟁 조건이 생긴다.
  let pendingAttach = null;

  function removeBanner() {
    // 최신 신호 우선 — 예약된 부착이 있으면 취소한다.
    if (pendingAttach) {
      document.removeEventListener("DOMContentLoaded", pendingAttach);
      pendingAttach = null;
    }
    const existing = document.getElementById(BANNER_ID);
    if (existing) {
      existing.remove();
    }
  }

  function showBanner(task) {
    removeBanner(); // idempotent — 기존 배너 제거 후 재생성.

    const banner = document.createElement("div");
    banner.id = BANNER_ID;
    banner.setAttribute("role", "status");
    Object.assign(banner.style, {
      position: "fixed",
      top: "0",
      left: "0",
      right: "0",
      zIndex: "2147483647",
      background: "#d32f2f",
      color: "#ffffff",
      font: "bold 14px/1.4 -apple-system, 'Apple SD Gothic Neo', sans-serif",
      textAlign: "center",
      padding: "6px 12px",
      pointerEvents: "none", // 사장님 클릭 방해 금지.
      boxShadow: "0 2px 6px rgba(0,0,0,0.35)"
    });

    let label = "🤖 자동화 작업 중 — Valuehire";
    if (typeof task === "string" && task.trim()) {
      label += " · " + task.trim();
    }
    banner.textContent = label;

    const attach = () => {
      pendingAttach = null;
      (document.body || document.documentElement).appendChild(banner);
    };
    if (document.body || document.documentElement) {
      attach();
    } else {
      pendingAttach = attach;
      document.addEventListener("DOMContentLoaded", attach, { once: true });
    }
  }

  window.addEventListener("valuehire:automation", (event) => {
    const detail = (event && event.detail) || {};
    if (detail.active === true) {
      showBanner(detail.task);
    } else {
      removeBanner();
    }
  });
})();
