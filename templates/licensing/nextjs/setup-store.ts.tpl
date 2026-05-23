import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type SetupStep = 'welcome' | 'database' | 'admin' | 'launch';

export interface LicenseData {
  type: string;
  email: string;
  expires: string;
  uses: number;
  max: number;
  product: string;
}

interface SetupState {
  currentStep: SetupStep;
  isCompleted: boolean;
  licenseKey: string;
  licenseData: LicenseData | null;
  databaseTested: boolean;
  adminCreated: boolean;
  setStep: (step: SetupStep) => void;
  setLicense: (key: string, data: LicenseData) => void;
  setDatabaseTested: (ok: boolean) => void;
  setAdminCreated: (ok: boolean) => void;
  complete: () => void;
  reset: () => void;
}

export const useSetupStore = create<SetupState>()(
  persist(
    (set) => ({
      currentStep: 'welcome',
      isCompleted: false,
      licenseKey: '',
      licenseData: null,
      databaseTested: false,
      adminCreated: false,
      setStep: (step) => set({ currentStep: step }),
      setLicense: (key, data) => set({ licenseKey: key, licenseData: data }),
      setDatabaseTested: (ok) => set({ databaseTested: ok }),
      setAdminCreated: (ok) => set({ adminCreated: ok }),
      complete: () => set({ isCompleted: true, currentStep: 'launch' }),
      reset: () =>
        set({
          currentStep: 'welcome',
          isCompleted: false,
          licenseKey: '',
          licenseData: null,
          databaseTested: false,
          adminCreated: false,
        }),
    }),
    { name: '__SLUG__-setup' }
  )
);
