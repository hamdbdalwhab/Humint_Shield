/**
 * Redux Toolkit store. Holds session state (tokens + user) and transient UI
 * state. Server data lives in React Query, not Redux.
 */
import { configureStore, createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { useDispatch, useSelector, type TypedUseSelectorHook } from 'react-redux';

import { tokenStore } from '@/api/client';
import type { User } from '@/types';

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  initialised: boolean;
}

const persistedAccess = tokenStore.getAccess();
const persistedRefresh = tokenStore.getRefresh();

const initialState: AuthState = {
  user: null,
  accessToken: persistedAccess,
  refreshToken: persistedRefresh,
  initialised: false,
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setSession(
      state,
      action: PayloadAction<{ user: User; access: string; refresh: string }>,
    ) {
      state.user = action.payload.user;
      state.accessToken = action.payload.access;
      state.refreshToken = action.payload.refresh;
      state.initialised = true;
      tokenStore.set(action.payload.access, action.payload.refresh);
    },
    setUser(state, action: PayloadAction<User | null>) {
      state.user = action.payload;
      state.initialised = true;
    },
    setAccessToken(state, action: PayloadAction<string>) {
      state.accessToken = action.payload;
      tokenStore.set(action.payload);
    },
    clearSession(state) {
      state.user = null;
      state.accessToken = null;
      state.refreshToken = null;
      state.initialised = true;
      tokenStore.clear();
    },
  },
});

interface UiState {
  sidebarOpen: boolean;
}

const uiSlice = createSlice({
  name: 'ui',
  initialState: { sidebarOpen: true } as UiState,
  reducers: {
    toggleSidebar(state) {
      state.sidebarOpen = !state.sidebarOpen;
    },
  },
});

export const { setSession, setUser, setAccessToken, clearSession } = authSlice.actions;
export const { toggleSidebar } = uiSlice.actions;

export const store = configureStore({
  reducer: {
    auth: authSlice.reducer,
    ui: uiSlice.reducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch: () => AppDispatch = useDispatch;
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;
