import { describe, expect, it } from 'vitest';

import {
  APP_TITLE,
  getDocumentTitle,
  getUserProfileDocumentTitle,
} from '../../src/components/layout/navigation';

describe('getDocumentTitle', () => {
  it('formats known routes with the app title suffix', () => {
    expect(getDocumentTitle('/')).toBe(`Dashboard | ${APP_TITLE}`);
    expect(getDocumentTitle('/users/42')).toBe(`User Profile | ${APP_TITLE}`);
    expect(getDocumentTitle('/mocks')).toBe(APP_TITLE);
    expect(getDocumentTitle('/experimental')).toBe(APP_TITLE);
  });

  it('uses the app title for unknown routes', () => {
    expect(getDocumentTitle('/missing')).toBe(APP_TITLE);
  });

  it('formats user profile titles with the resolved username', () => {
    expect(getUserProfileDocumentTitle('alice')).toBe(`alice | ${APP_TITLE}`);
    expect(getUserProfileDocumentTitle('@alice')).toBe(`alice | ${APP_TITLE}`);
    expect(getUserProfileDocumentTitle(undefined)).toBe(`User Profile | ${APP_TITLE}`);
  });
});
