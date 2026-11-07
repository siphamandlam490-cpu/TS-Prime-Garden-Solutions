(() => {
  const description = document.getElementById("work_description");
  const count = document.getElementById("description-count");
  const photoInput = document.getElementById("photo");
  const photoName = document.getElementById("photo-name");
  const photoPreview = document.getElementById("photo-preview");
  let previewUrl = null;

  if (description && count) {
    const updateCount = () => { count.textContent = `${description.value.length} / 2000`; };
    description.addEventListener("input", updateCount);
    updateCount();
  }

  function showPhoto(file) {
    if (!file || !photoInput || !photoName || !photoPreview) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    photoPreview.hidden = true;
    photoPreview.removeAttribute("src");
    photoName.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
    if (file.size > 5 * 1024 * 1024) {
      photoName.textContent += " — file is too large; choose a photo under 5 MB.";
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      photoName.textContent += " — choose a JPG, PNG or WebP image.";
      return;
    }
    previewUrl = URL.createObjectURL(file);
    photoPreview.src = previewUrl;
    photoPreview.hidden = false;
  }

  if (photoInput) photoInput.addEventListener("change", () => showPhoto(photoInput.files && photoInput.files[0]));

  const dialog = document.getElementById("camera-dialog");
  const openButton = document.getElementById("camera-open");
  const closeButton = document.getElementById("camera-close");
  const captureButton = document.getElementById("camera-capture");
  const video = document.getElementById("camera-video");
  const canvas = document.getElementById("camera-canvas");
  const error = document.getElementById("camera-error");
  let stream = null;

  function closeCamera() {
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    if (video) video.srcObject = null;
    if (dialog) dialog.hidden = true;
    if (openButton) openButton.focus();
  }

  if (openButton && dialog && video) {
    openButton.addEventListener("click", async () => {
      error.textContent = "";
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        error.textContent = "Camera access is unavailable here. Open this site on localhost or HTTPS, or choose an existing photo.";
        dialog.hidden = false;
        return;
      }
      dialog.hidden = false;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1600 } },
          audio: false
        });
        video.srcObject = stream;
        await video.play();
        captureButton.focus();
      } catch (cameraError) {
        const messages = {
          NotAllowedError: "Camera permission was blocked. Allow camera access in your browser settings, then try again.",
          NotFoundError: "No camera was found. You can choose an existing photo instead.",
          NotReadableError: "The camera is busy in another app. Close that app and try again."
        };
        error.textContent = messages[cameraError.name] || "The camera could not be opened. Choose an existing photo instead.";
      }
    });
    closeButton.addEventListener("click", closeCamera);
    dialog.addEventListener("click", event => { if (event.target === dialog) closeCamera(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape" && !dialog.hidden) closeCamera(); });
    captureButton.addEventListener("click", () => {
      if (!video.videoWidth || !video.videoHeight) {
        error.textContent = "The camera is still starting. Wait a moment and try again.";
        return;
      }
      const scale = Math.min(1, 2400 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(blob => {
        if (!blob) {
          error.textContent = "The photo could not be captured. Please try again.";
          return;
        }
        if (blob.size > 5 * 1024 * 1024) {
          error.textContent = "The photo is over 5 MB. Move closer or use a smaller image.";
          return;
        }
        const file = new File([blob], `garden-photo-${Date.now()}.jpg`, { type: "image/jpeg" });
        const transfer = new DataTransfer();
        transfer.items.add(file);
        photoInput.files = transfer.files;
        showPhoto(file);
        closeCamera();
      }, "image/jpeg", 0.86);
    });
  }
})();
