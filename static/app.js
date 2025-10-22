(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', () => {
    initAvatarFallbacks();
    initExportForm();
    initProfilePreview();
  });

  function initAvatarFallbacks(context) {
    const scope = context || document;
    scope.querySelectorAll('[data-avatar] img').forEach((img) => {
      if (img.dataset.avatarBound === 'true') {
        return;
      }
      img.dataset.avatarBound = 'true';
      img.addEventListener('error', () => {
        const wrapper = img.closest('[data-avatar]');
        if (wrapper) {
          wrapper.classList.add('avatar--fallback');
        }
      });
      if (!img.getAttribute('src')) {
        const wrapper = img.closest('[data-avatar]');
        if (wrapper) {
          wrapper.classList.add('avatar--fallback');
        }
      }
    });
  }

  function initExportForm() {
    const exportForm = document.querySelector('[data-export-form]');
    if (!exportForm) {
      return;
    }

    const progressWrapper = document.querySelector('[data-export-progress]');
    const progressBar = progressWrapper ? progressWrapper.querySelector('.progress-bar') : null;
    const progressStatus = progressWrapper ? progressWrapper.querySelector('[data-export-status]') : null;
    const submitButton = exportForm.querySelector('[data-export-submit]');
    let progressInterval = null;

    exportForm.addEventListener('submit', async (event) => {
      event.preventDefault();

      if (submitButton) {
        submitButton.disabled = true;
      }

      if (progressWrapper && progressBar && progressStatus) {
        progressWrapper.classList.remove('d-none');
        progressWrapper.classList.remove('export-progress--error');
        setProgress(8, 'Preparing export…');
        startProgressSimulation();
      }

      try {
        const formData = new FormData(exportForm);
        const response = await fetch(exportForm.action, {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });

        if (response.redirected) {
          window.location.href = response.url;
          return;
        }

        if (!response.ok) {
          throw new Error('Export failed');
        }

        stopProgressSimulation();
        updateProgress(82, 'Packaging download…');

        const disposition = response.headers.get('Content-Disposition') || '';
        const matches = disposition.match(/filename="?([^";]+)"?/i);
        const requestedFormat = String(formData.get('export_format') || 'csv');
        const filename = matches ? matches[1] : `export.${requestedFormat}`;
        const blob = await response.blob();

        updateProgress(100, 'Download ready!');

        const downloadLink = document.createElement('a');
        const url = window.URL.createObjectURL(blob);
        downloadLink.href = url;
        downloadLink.download = filename;
        document.body.appendChild(downloadLink);
        downloadLink.click();
        downloadLink.remove();
        window.setTimeout(() => {
          window.URL.revokeObjectURL(url);
        }, 1000);

        window.setTimeout(() => {
          hideProgress();
        }, 2000);
      } catch (error) {
        stopProgressSimulation();
        updateProgress(0, 'Export failed. Please try again.');
        if (progressWrapper) {
          progressWrapper.classList.add('export-progress--error');
          window.setTimeout(() => {
            hideProgress();
            progressWrapper.classList.remove('export-progress--error');
          }, 4000);
        }
        console.error(error);
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
        }
      }
    });

    function setProgress(value) {
      if (!progressBar) {
        return;
      }
      const clamped = Math.max(0, Math.min(100, value));
      progressBar.style.width = `${clamped}%`;
      progressBar.setAttribute('aria-valuenow', String(clamped));
    }

    function updateProgress(value, message) {
      setProgress(value);
      if (progressStatus) {
        progressStatus.textContent = message;
      }
    }

    function startProgressSimulation() {
      stopProgressSimulation();
      let current = 12;
      updateProgress(current, 'Processing followers…');
      progressInterval = window.setInterval(() => {
        current += Math.max(3, Math.round(Math.random() * 12));
        if (current >= 76) {
          current = 76;
          stopProgressSimulation();
        }
        updateProgress(current, current < 50 ? 'Crunching numbers…' : 'Almost there…');
      }, 800);
    }

    function stopProgressSimulation() {
      if (progressInterval) {
        window.clearInterval(progressInterval);
        progressInterval = null;
      }
    }

    function hideProgress(clearMessage = true) {
      if (!progressWrapper) {
        return;
      }
      progressWrapper.classList.add('d-none');
      if (clearMessage) {
        updateProgress(0, '');
      } else {
        setProgress(0);
      }
    }
  }

  function initProfilePreview() {
    const input = document.querySelector('[data-username-input]');
    const preview = document.querySelector('[data-profile-preview]');
    if (!input || !preview) {
      return;
    }

    const image = preview.querySelector('[data-profile-image]');
    const fallback = preview.querySelector('[data-profile-fallback]');
    const avatarWrapper = preview.querySelector('[data-avatar]');
    let debounceTimer = null;

    const update = () => {
      const value = (input.value || '').trim().replace(/^@+/, '');
      if (!value) {
        preview.classList.add('d-none');
        if (image) {
          image.removeAttribute('src');
        }
        if (avatarWrapper) {
          avatarWrapper.classList.add('avatar--fallback');
        }
        if (fallback) {
          fallback.textContent = '@';
        }
        return;
      }

      preview.classList.remove('d-none');
      const initial = value.charAt(0).toUpperCase();
      if (fallback) {
        fallback.textContent = initial || '@';
      }
      if (avatarWrapper) {
        avatarWrapper.classList.remove('avatar--fallback');
      }
      if (image) {
        const url = `https://unavatar.io/instagram/${encodeURIComponent(value)}`;
        if (image.getAttribute('src') !== url) {
          image.src = url;
        }
      }
      initAvatarFallbacks(preview);
    };

    input.addEventListener('input', () => {
      if (debounceTimer) {
        window.clearTimeout(debounceTimer);
      }
      debounceTimer = window.setTimeout(update, 250);
    });

    update();
  }
})();
