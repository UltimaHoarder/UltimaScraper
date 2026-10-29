import { useEffect } from 'react';
import { createPortal } from 'react-dom';

import './ImageLightbox.css';

interface ImageLightboxProps {
  imageUrl: string | null;
  alt: string;
  onClose: () => void;
}

export function ImageLightbox({ imageUrl, alt, onClose }: ImageLightboxProps) {
  useEffect(() => {
    if (!imageUrl) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [imageUrl, onClose]);

  if (!imageUrl || typeof document === 'undefined') {
    return null;
  }

  return createPortal(
    <div
      className="lightbox-overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Image preview"
    >
      <div className="lightbox-content" onClick={(event) => event.stopPropagation()}>
        <button
          type="button"
          className="lightbox-close"
          onClick={onClose}
          aria-label="Close image preview"
        >
          ×
        </button>
        <img src={imageUrl} alt={alt} className="lightbox-image" />
      </div>
    </div>,
    document.body,
  );
}