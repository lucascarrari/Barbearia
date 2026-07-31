function csrfToken() {
  const token = document.querySelector('meta[name="csrf-token"]');
  return token ? token.content : "";
}

function formatPhone(value) {
  const digits = value.replace(/\D/g, "").slice(0, 11);
  if (digits.length <= 10) {
    return digits.replace(/(\d{2})(\d{4})(\d{0,4})/, "($1) $2-$3").trim();
  }
  return digits.replace(/(\d{2})(\d{5})(\d{0,4})/, "($1) $2-$3").trim();
}

function dismissToast(item) {
  item.classList.add("toast-leaving");
  window.setTimeout(() => item.remove(), 250);
}

function scheduleToastDismiss(item, timeout = 5000) {
  window.setTimeout(() => dismissToast(item), timeout);
}

document.querySelectorAll(".toast").forEach((item) => scheduleToastDismiss(item));

document.addEventListener("input", (event) => {
  if (event.target && event.target.name === "phone") {
    event.target.value = formatPhone(event.target.value);
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.matches("[data-confirm-submit]")) {
    const question = form.dataset.confirmSubmit;
    if (question && !window.confirm(question)) {
      event.preventDefault();
    }
    return;
  }
  if (!form.matches("[data-ajax-action]")) return;
  const question = form.dataset.confirm;
  if (question && !window.confirm(question)) {
    event.preventDefault();
    return;
  }
  event.preventDefault();
  const button = form.querySelector("button");
  if (button) {
    button.disabled = true;
    button.dataset.originalText = button.textContent;
    button.textContent = "Salvando...";
  }
  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest"
      },
      body: new FormData(form)
    });
    const data = await response.json();
    window.dispatchEvent(new CustomEvent("flash", { detail: data.message || "Atualizado." }));
    if (response.ok) window.setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    window.dispatchEvent(new CustomEvent("flash", { detail: "Nao foi possivel concluir a acao." }));
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = button.dataset.originalText;
    }
  }
});

window.addEventListener("flash", (event) => {
  const stack = document.querySelector(".toast-stack") || document.createElement("div");
  stack.className = "toast-stack";
  const item = document.createElement("div");
  item.className = "toast";
  item.textContent = event.detail;
  stack.appendChild(item);
  document.body.appendChild(stack);
  scheduleToastDismiss(item);
});

async function refreshAvailability(form) {
  const box = form.querySelector("[data-availability-box]");
  const timeSelect = form.querySelector("[data-time-select]");
  const service = form.querySelector('[name="service"]').value;
  const barber = form.querySelector('[name="barber"]').value;
  const date = form.querySelector('[name="date"]').value;
  if (!box || !service || !barber || !date) return;
  box.textContent = "Consultando horarios...";
  if (timeSelect) {
    timeSelect.innerHTML = '<option value="">Consultando...</option>';
  }
  try {
    const params = new URLSearchParams({ service, barber, date });
    const response = await fetch(`/api/availability/?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Erro");
    box.innerHTML = "";
    const availableSlots = data.slots.filter((slot) => slot.available);
    if (timeSelect) {
      timeSelect.innerHTML = '<option value="">Selecione um horario</option>';
    }
    if (!availableSlots.length) {
      box.textContent = "Nenhum horario disponivel para esta combinacao.";
      if (timeSelect) {
        timeSelect.innerHTML = '<option value="">Sem horarios disponiveis</option>';
      }
      return;
    }
    availableSlots.forEach((slot) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "slot-choice";
      button.textContent = slot.time;
      button.addEventListener("click", () => {
        if (timeSelect) {
          timeSelect.value = slot.time;
        }
      });
      box.appendChild(button);
      if (timeSelect) {
        const option = document.createElement("option");
        option.value = slot.time;
        option.textContent = slot.time;
        timeSelect.appendChild(option);
      }
    });
  } catch (error) {
    box.textContent = "Nao foi possivel consultar a agenda agora.";
    if (timeSelect) {
      timeSelect.innerHTML = '<option value="">Consulte novamente</option>';
    }
  }
}

document.querySelectorAll("[data-availability-form]").forEach((form) => {
  ["service", "barber", "date"].forEach((name) => {
    const field = form.querySelector(`[name="${name}"]`);
    if (field) field.addEventListener("change", () => refreshAvailability(form));
  });
});
