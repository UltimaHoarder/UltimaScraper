import type { DRMConfig } from '../../../api/types/setup';
import { PathField } from '../../../components/shared/PathPicker';
import { SetupHint } from './SetupHint';

interface SetupDrmStepProps {
  drmConfig: DRMConfig;
  setDrmConfig: (cfg: DRMConfig) => void;
  onBack: () => void;
  onNext: () => void;
}

export function SetupDrmStep({
  drmConfig,
  setDrmConfig,
  onBack,
  onNext,
}: SetupDrmStepProps) {
  const update = (field: keyof DRMConfig, value: string) =>
    setDrmConfig({ ...drmConfig, [field]: value || null });

  return (
    <>
      <div className="setup-card-header">
        <h2>DRM Configuration</h2>
        <p>
          Optional. Point to a Widevine device to download protected media. You can skip this and
          add it later in Settings.
        </p>
      </div>

      <div className="setup-card-body">
        <div className="setup-form-group">
          <label className="setup-form-label">
            Device Client Blob Filepath
            <SetupHint text="The client ID blob file from your Widevine device dump, on the server. On Docker it must be inside a mounted folder." />
          </label>
          <PathField
            mode="file"
            label="Choose the device client blob"
            value={drmConfig.device_client_blob_filepath || ''}
            onChange={(value) => update('device_client_blob_filepath', value)}
            placeholder="/path/to/device_client_id_blob"
          />
        </div>

        <div className="setup-form-group">
          <label className="setup-form-label">
            Device Private Key Filepath
            <SetupHint text="The private key file from the same Widevine device dump." />
          </label>
          <PathField
            mode="file"
            label="Choose the device private key"
            value={drmConfig.device_private_key_filepath || ''}
            onChange={(value) => update('device_private_key_filepath', value)}
            placeholder="/path/to/device_private_key"
          />
        </div>
      </div>

      <div className="setup-card-footer">
        <button onClick={onBack} className="btn-secondary btn-lg">
          Back
        </button>
        <button onClick={onNext} className="btn-primary btn-lg">
          {drmConfig.device_client_blob_filepath || drmConfig.device_private_key_filepath
            ? 'Continue'
            : 'Skip'}
        </button>
      </div>
    </>
  );
}
