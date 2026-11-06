import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  getAgeVerification,
  getIdentityVerification,
} from '../../../api/auths';
import type {
  AgeVerificationResponse,
  AuthCredential,
} from '../../../api/types/auths';
import { copyText } from '../../../utils/clipboard';

interface VerificationModalContent {
  kind: 'age' | 'identity';
  title: string;
  loadingText: string;
  infoText: string;
  qrAlt: string;
  openLabel: string;
  getVerification: (
    authId: number,
    site: string,
  ) => Promise<AgeVerificationResponse>;
}

interface VerificationModalProps {
  auth: AuthCredential;
  requestKey: string;
  onClose: () => void;
  content: VerificationModalContent;
}

const AGE_VERIFICATION_MODAL_CONTENT: VerificationModalContent = {
  kind: 'age',
  title: '🔞 Age Verification Required',
  loadingText: 'Getting verification URL...',
  infoText: 'Complete age verification for',
  qrAlt: 'Age Verification QR Code',
  openLabel: '🔗 Open',
  getVerification: (authId, site) => getAgeVerification(authId, site),
};

const IDENTITY_VERIFICATION_MODAL_CONTENT: VerificationModalContent = {
  kind: 'identity',
  title: '🪪 Identity Verification',
  loadingText: 'Getting identity verification URL...',
  infoText: 'Open the identity verification flow for',
  qrAlt: 'Identity Verification QR Code',
  openLabel: '🪪 Open',
  getVerification: (authId, site) => getIdentityVerification(authId, site),
};

function VerificationModal({
  auth,
  requestKey,
  onClose,
  content,
}: VerificationModalProps) {
  const [copySuccess, setCopySuccess] = useState(false);
  const queryClient = useQueryClient();
  const { data: verificationData, isLoading } = useQuery({
    queryKey: ['auth-verification', content.kind, auth.id, auth.site, requestKey],
    queryFn: async () => {
      try {
        return await content.getVerification(auth.id, auth.site);
      } catch (error) {
        return {
          success: false,
          redirect_url: null,
          api_flow: null,
          error:
            error instanceof Error
              ? error.message
              : 'Failed to get verification URL',
        } satisfies AgeVerificationResponse;
      }
    },
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const handleCopyLink = async () => {
    if (!verificationData?.redirect_url) {
      return;
    }
    try {
      await copyText(verificationData.redirect_url);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch {
      const textArea = document.createElement('textarea');
      textArea.value = verificationData.redirect_url;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    }
  };

  const handleOpenLink = () => {
    if (verificationData?.redirect_url) {
      window.open(verificationData.redirect_url, '_blank', 'noopener,noreferrer');
    }
  };

  const getQrCodeUrl = (url: string) => {
    return `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(
      url,
    )}`;
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content age-verification-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2>{content.title}</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {isLoading ? (
            <div className="loading-state">
              <div className="spinner"></div>
              <p>{content.loadingText}</p>
            </div>
          ) : verificationData?.success && verificationData.redirect_url ? (
            <div className="verification-content">
              <p className="verification-info">
                {content.infoText}{' '}
                <strong>{auth.username || `Auth #${auth.id}`}</strong> by visiting
                the link below or scanning the QR code.
              </p>

              <div className="qr-code-container">
                <img
                  src={getQrCodeUrl(verificationData.redirect_url)}
                  alt={content.qrAlt}
                  className="qr-code"
                />
              </div>

              <div className="verification-link-container">
                <input
                  type="text"
                  readOnly
                  value={verificationData.redirect_url}
                  className="verification-link-input"
                />
                <div className="verification-link-actions">
                  <button className="action-btn copy-btn" onClick={handleCopyLink}>
                    {copySuccess ? '✅ Copied!' : '📋 Copy'}
                  </button>
                  <button className="action-btn open-btn" onClick={handleOpenLink}>
                    {content.openLabel}
                  </button>
                </div>
              </div>

              {verificationData.api_flow && (
                <p className="verification-flow">
                  Flow: {verificationData.api_flow}
                </p>
              )}
            </div>
          ) : (
            <div className="error-state">
              <p className="error-icon">❌</p>
              <p className="error-message">
                {verificationData?.error || 'Failed to get verification URL'}
              </p>
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button
            type="button"
            className="btn-cancel"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['auths'] });
              onClose();
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export function AgeVerificationModal(props: {
  auth: AuthCredential;
  requestKey: string;
  onClose: () => void;
}) {
  return <VerificationModal {...props} content={AGE_VERIFICATION_MODAL_CONTENT} />;
}

export function IdentityVerificationModal(props: {
  auth: AuthCredential;
  requestKey: string;
  onClose: () => void;
}) {
  return (
    <VerificationModal {...props} content={IDENTITY_VERIFICATION_MODAL_CONTENT} />
  );
}
