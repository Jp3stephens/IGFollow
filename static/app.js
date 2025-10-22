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
        setProgress(10);
        updateProgress(10, 'Preparing export…');
        startProgressSimulation();
      }

      try {
        const formData = new FormData(exportForm);
        const response = await fetch(exportForm.action, {
          method: 'POST',
          body: formData,
          credentials: 'include',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            Accept: 'application/json',
            'X-CSRFToken': getCsrfToken(exportForm),
          },
        });

        const requestedFormat = String(formData.get('export_format') || 'csv');
        const payload = await parseJson(response);

        if (!response.ok) {
          const errorMessage = payload.message || 'Export failed. Please try again.';
          throw new Error(errorMessage);
        }

        if (payload.status === 'error') {
          const errorMessage = payload.message || 'Export failed. Please try again.';
          throw new Error(errorMessage);
        }

        if (payload.status === 'redirect' && payload.url) {
          window.location.href = payload.url;
          return;
        }

        if (payload.status !== 'ok' || !payload.download_url) {
          const errorMessage = payload.message || 'Export failed. Please try again.';
          throw new Error(errorMessage);
        }

        stopProgressSimulation();
        updateProgress(86, 'Packaging download…');

        triggerDownload(payload.download_url, requestedFormat);

        updateProgress(100, 'Download ready! Your download should begin shortly.');

        window.setTimeout(() => {
          hideProgress(false);
        }, 2200);
      } catch (error) {
        stopProgressSimulation();
        updateProgress(0, error.message || 'Export failed. Please try again.');
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

    async function parseJson(response) {
      const text = await response.text();
      try {
        return text ? JSON.parse(text) : {};
      } catch (error) {
        console.error('Failed to parse JSON response', error);
        return {};
      }
    }

    function triggerDownload(downloadUrl, requestedFormat) {
      if (!downloadUrl) {
        return;
      }

      const url = appendCacheBuster(downloadUrl);

      if (window.navigator && typeof window.navigator.msSaveOrOpenBlob === 'function') {
        window.location.href = url;
        return;
      }

      let downloadFrame = document.querySelector('[data-export-download-frame]');
      if (!downloadFrame) {
        downloadFrame = document.createElement('iframe');
        downloadFrame.setAttribute('aria-hidden', 'true');
        downloadFrame.setAttribute('tabindex', '-1');
        downloadFrame.style.display = 'none';
        downloadFrame.dataset.exportDownloadFrame = 'true';
        document.body.appendChild(downloadFrame);
      }

      downloadFrame.src = url;

      const completionMessage = requestedFormat === 'xlsx' ? 'Excel download requested.' : 'CSV download requested.';
      if (progressStatus && !progressStatus.textContent) {
        progressStatus.textContent = completionMessage;
      }
    }

    function appendCacheBuster(url) {
      try {
        const parsed = new URL(url, window.location.origin);
        parsed.searchParams.set('_', Date.now().toString());
        return parsed.toString();
      } catch (error) {
        return url;
      }
    }
  }

  function getCsrfToken(scope) {
    if (scope) {
      const field = scope.querySelector('input[name="csrf_token"]');
      if (field && field.value) {
        return field.value;
      }
    }
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') || '' : '';
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
