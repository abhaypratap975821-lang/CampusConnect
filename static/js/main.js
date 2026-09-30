document.addEventListener('DOMContentLoaded', () => {
  // Cross-browser dark dropdowns. Native <select> option popups can ignore page CSS
  // on Windows/Chrome, so these controls use a small custom menu while keeping
  // the original select in the form as the real submitted field.
  const setupDarkSelects = (scope = document) => {
    scope.querySelectorAll('select.cc-dark-select:not([data-dark-select-ready])').forEach((select) => {
      select.setAttribute('data-dark-select-ready', '1');

      const shell = document.createElement('div');
      shell.className = 'cc-select-shell';

      const trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'cc-select-trigger';
      trigger.setAttribute('aria-haspopup', 'listbox');
      trigger.setAttribute('aria-expanded', 'false');

      const menu = document.createElement('div');
      menu.className = 'cc-select-menu';
      menu.setAttribute('role', 'listbox');
      menu.hidden = true;

      const sync = () => {
        const selected = select.options[select.selectedIndex];
        trigger.textContent = selected ? selected.textContent : '';
        menu.querySelectorAll('[role="option"]').forEach((item) => {
          const active = item.dataset.value === select.value;
          item.setAttribute('aria-selected', active ? 'true' : 'false');
          item.classList.toggle('is-selected', active);
        });
      };

      Array.from(select.options).forEach((option) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'cc-select-option';
        item.dataset.value = option.value;
        item.textContent = option.textContent;
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', option.selected ? 'true' : 'false');
        item.disabled = option.disabled;
        item.addEventListener('click', () => {
          if (option.disabled) return;
          select.value = option.value;
          select.dispatchEvent(new Event('change', {bubbles: true}));
          sync();
          menu.hidden = true;
          trigger.setAttribute('aria-expanded', 'false');
          trigger.focus();
        });
        menu.appendChild(item);
      });

      trigger.addEventListener('click', () => {
        const open = !menu.hidden;
        document.querySelectorAll('.cc-select-menu').forEach((other) => { other.hidden = true; });
        document.querySelectorAll('.cc-select-trigger').forEach((other) => { other.setAttribute('aria-expanded', 'false'); });
        menu.hidden = open;
        trigger.setAttribute('aria-expanded', open ? 'false' : 'true');
      });

      select.addEventListener('change', sync);
      shell.append(trigger, menu);
      select.parentNode.insertBefore(shell, select);
      shell.appendChild(select);
      select.classList.add('cc-dark-select-native');
      sync();
    });
  };

  setupDarkSelects();
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.cc-select-shell')) {
      document.querySelectorAll('.cc-select-menu').forEach((menu) => { menu.hidden = true; });
      document.querySelectorAll('.cc-select-trigger').forEach((button) => { button.setAttribute('aria-expanded', 'false'); });
    }
  });
  document.querySelectorAll('[data-modal-open]').forEach((button) => {
    button.addEventListener('click', () => document.getElementById(button.dataset.modalOpen)?.classList.add('active'));
  });
  document.querySelectorAll('[data-modal-close]').forEach((button) => {
    button.addEventListener('click', () => button.closest('.modal')?.classList.remove('active'));
  });
  document.querySelectorAll('.modal').forEach((modal) => modal.addEventListener('click', (event) => {
    if (event.target === modal) modal.classList.remove('active');
  }));

  window.setTimeout(() => document.querySelectorAll('.toast').forEach((toast) => {
    toast.style.opacity = '0'; toast.style.transform = 'translateY(8px)';
  }), 4200);

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion) return;

  // Subtle pointer parallax; no dependency and no layout reads in the hot path.
  const parallax = document.querySelectorAll('.anime-parallax');
  const landing = document.querySelector('.anime-landing');
  if (parallax.length || landing) {
    window.addEventListener('pointermove', (event) => {
      const x = (event.clientX / window.innerWidth - 0.5) * 2;
      const y = (event.clientY / window.innerHeight - 0.5) * 2;
      parallax.forEach((el) => {
        el.style.transform = `translate3d(${x * 7}px, ${y * 5}px, 0)`;
      });
      if (landing) {
        landing.style.setProperty('--mx', `${event.clientX}px`);
        landing.style.setProperty('--my', `${event.clientY}px`);
      }
    }, {passive:true});
  }

  // Small card tilt on desktop pointer devices only.
  if (window.matchMedia('(pointer:fine)').matches) {
    document.querySelectorAll('.person-card, .anime-showcase-card').forEach((card) => {
      card.addEventListener('pointermove', (event) => {
        const rect = card.getBoundingClientRect();
        const rx = ((event.clientY - rect.top) / rect.height - 0.5) * -4;
        const ry = ((event.clientX - rect.left) / rect.width - 0.5) * 4;
        card.style.transform = `perspective(800px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-2px)`;
      });
      card.addEventListener('pointerleave', () => { card.style.transform = ''; });
    });
  }

  // Shared app-banner parallax keeps every inner page visually alive.
  const appBanner = document.querySelector('.app-art-banner');
  if (appBanner && window.matchMedia('(pointer:fine)').matches) {
    appBanner.addEventListener('pointermove', (event) => {
      const rect = appBanner.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      appBanner.style.setProperty('--art-x', `${x * 10}px`);
      appBanner.style.setProperty('--art-y', `${y * 7}px`);
    });
    appBanner.addEventListener('pointerleave', () => {
      appBanner.style.setProperty('--art-x', '0px');
      appBanner.style.setProperty('--art-y', '0px');
    });
  }

  // Accessible click feedback for buttons, without changing their form behavior.
  document.querySelectorAll('.button, .icon-action').forEach((button) => {
    button.addEventListener('pointerdown', () => {
      button.classList.add('is-pressed');
      window.setTimeout(() => button.classList.remove('is-pressed'), 150);
    });
  });
});
