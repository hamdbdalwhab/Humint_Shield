/**
 * "Midnight Cyber" design system.
 *
 * A deep-space command-centre palette with cyan/violet neon accents, frosted
 * glass surfaces and Arabic-first typography. All interactive surfaces share
 * the same glow language so the product feels like one instrument rather than
 * a collection of pages.
 */
import { alpha, createTheme } from '@mui/material/styles';

export const palette = {
  background: '#0A0F1C',
  surface: '#151E32',
  surfaceRaised: '#1B2740',
  primary: '#00F0FF',
  secondary: '#7000FF',
  success: '#00E676',
  danger: '#FF1744',
  warning: '#FFB020',
  info: '#38BDF8',
  text: '#E2E8F0',
  muted: '#8B9BB4',
  line: 'rgba(255,255,255,0.10)',
  glass: 'rgba(21, 30, 50, 0.70)',
} as const;

const shadow = {
  card: '0 24px 70px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.05)',
  cyan: `0 0 0 1px ${alpha(palette.primary, 0.35)}, 0 0 28px ${alpha(palette.primary, 0.28)}`,
  violet: `0 0 0 1px ${alpha(palette.secondary, 0.45)}, 0 0 34px ${alpha(palette.secondary, 0.32)}`,
  danger: `0 0 0 1px ${alpha(palette.danger, 0.45)}, 0 0 28px ${alpha(palette.danger, 0.35)}`,
};

export const theme = createTheme({
  direction: 'rtl',
  palette: {
    mode: 'dark',
    primary: { main: palette.primary, dark: '#00A9B8', light: '#7DFBFF', contrastText: '#031018' },
    secondary: { main: palette.secondary, dark: '#4B00B8', light: '#B388FF', contrastText: '#ffffff' },
    error: { main: palette.danger, light: '#FF616F', dark: '#C4002B' },
    warning: { main: palette.warning, light: '#FFD166', dark: '#B77900' },
    success: { main: palette.success, light: '#66FFA6', dark: '#00A64F' },
    info: { main: palette.info, light: '#7DD3FC', dark: '#0284C7' },
    background: { default: palette.background, paper: palette.surface },
    text: { primary: palette.text, secondary: palette.muted, disabled: '#5C6B84' },
    divider: palette.line,
    action: {
      hover: 'rgba(0, 240, 255, 0.06)',
      selected: 'rgba(0, 240, 255, 0.12)',
      focus: 'rgba(0, 240, 255, 0.12)',
    },
  },
  shape: { borderRadius: 16 },
  typography: {
    fontFamily: ['Cairo', 'Tajawal', 'Segoe UI', 'Tahoma', 'sans-serif'].join(','),
    h1: { fontSize: '2.15rem', fontWeight: 800, letterSpacing: '-0.02em' },
    h2: { fontSize: '1.65rem', fontWeight: 800, letterSpacing: '-0.015em' },
    h3: { fontSize: '1.18rem', fontWeight: 700 },
    h4: { fontSize: '2rem', fontWeight: 800, letterSpacing: '-0.02em' },
    h5: { fontSize: '1.1rem', fontWeight: 700 },
    h6: { fontSize: '0.95rem', fontWeight: 700 },
    subtitle1: { fontWeight: 700 },
    subtitle2: { fontWeight: 700 },
    button: { textTransform: 'none', fontWeight: 700, letterSpacing: 0 },
    overline: { letterSpacing: '0.14em', fontWeight: 700, fontSize: '0.68rem' },
    body1: { lineHeight: 1.75 },
    body2: { lineHeight: 1.7 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        ':root': {
          colorScheme: 'dark',
        },
        body: {
          minHeight: '100vh',
          backgroundColor: palette.background,
          backgroundImage: [
            `radial-gradient(circle at 12% 8%, ${alpha(palette.secondary, 0.22)}, transparent 32%)`,
            `radial-gradient(circle at 88% 12%, ${alpha(palette.primary, 0.16)}, transparent 30%)`,
            `radial-gradient(circle at 50% 100%, ${alpha('#1D4ED8', 0.12)}, transparent 42%)`,
            'linear-gradient(180deg, #0A0F1C 0%, #070B14 100%)',
          ].join(','),
          backgroundAttachment: 'fixed',
        },
        '::selection': {
          background: alpha(palette.primary, 0.35),
          color: '#ffffff',
        },
        '*::-webkit-scrollbar': { width: 10, height: 10 },
        '*::-webkit-scrollbar-track': { background: 'rgba(255,255,255,0.03)' },
        '*::-webkit-scrollbar-thumb': {
          background: `linear-gradient(180deg, ${alpha(palette.primary, 0.55)}, ${alpha(palette.secondary, 0.55)})`,
          borderRadius: 99,
          border: '2px solid #0A0F1C',
        },
      },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: palette.glass,
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          border: `1px solid ${palette.line}`,
          boxShadow: shadow.card,
          backgroundClip: 'padding-box',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          position: 'relative',
          overflow: 'hidden',
          borderRadius: 20,
          background: `linear-gradient(145deg, rgba(27,39,64,0.86), rgba(15,23,40,0.72))`,
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
          border: `1px solid ${palette.line}`,
          boxShadow: shadow.card,
          transition: 'transform 220ms ease, box-shadow 220ms ease, border-color 220ms ease',
          '&::before': {
            content: '""',
            position: 'absolute',
            inset: 0,
            pointerEvents: 'none',
            background:
              'linear-gradient(120deg, rgba(255,255,255,0.055), transparent 28%, transparent 72%, rgba(0,240,255,0.045))',
          },
          '&:hover': {
            borderColor: alpha(palette.primary, 0.28),
            boxShadow: `${shadow.card}, 0 0 32px ${alpha(palette.primary, 0.10)}`,
          },
        },
      },
    },
    MuiCardContent: {
      styleOverrides: { root: { position: 'relative', zIndex: 1 } },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          borderRadius: 12,
          paddingInline: 20,
          minHeight: 42,
          transition: 'transform 160ms ease, box-shadow 220ms ease, background 220ms ease',
          '&:active': { transform: 'scale(0.97)' },
        },
        containedPrimary: {
          color: '#031018',
          background: `linear-gradient(135deg, ${palette.primary} 0%, #6EF7FF 50%, #36D7E8 100%)`,
          boxShadow: `0 0 22px ${alpha(palette.primary, 0.34)}`,
          '&:hover': {
            background: `linear-gradient(135deg, #5AF6FF 0%, ${palette.primary} 100%)`,
            boxShadow: `0 0 36px ${alpha(palette.primary, 0.55)}, 0 0 0 1px ${alpha(palette.primary, 0.55)}`,
          },
        },
        containedSecondary: {
          background: `linear-gradient(135deg, ${palette.secondary} 0%, #9D4DFF 100%)`,
          boxShadow: `0 0 24px ${alpha(palette.secondary, 0.38)}`,
          '&:hover': {
            boxShadow: `0 0 38px ${alpha(palette.secondary, 0.6)}`,
          },
        },
        containedError: {
          background: `linear-gradient(135deg, ${palette.danger} 0%, #FF5C7A 100%)`,
          boxShadow: `0 0 24px ${alpha(palette.danger, 0.32)}`,
        },
        containedSuccess: {
          color: '#00160A',
          background: `linear-gradient(135deg, ${palette.success} 0%, #7CFFB2 100%)`,
          boxShadow: `0 0 24px ${alpha(palette.success, 0.30)}`,
        },
        outlined: {
          borderColor: alpha(palette.primary, 0.35),
          backgroundColor: 'rgba(0,240,255,0.03)',
          '&:hover': {
            borderColor: palette.primary,
            backgroundColor: alpha(palette.primary, 0.08),
            boxShadow: `0 0 18px ${alpha(palette.primary, 0.18)}`,
          },
        },
        text: {
          '&:hover': { backgroundColor: alpha(palette.primary, 0.07) },
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          transition: 'background 180ms ease, color 180ms ease, box-shadow 180ms ease',
          '&:hover': {
            backgroundColor: alpha(palette.primary, 0.10),
            color: palette.primary,
            boxShadow: `0 0 16px ${alpha(palette.primary, 0.18)}`,
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          fontWeight: 700,
          border: '1px solid rgba(255,255,255,0.08)',
          backdropFilter: 'blur(8px)',
        },
        colorPrimary: {
          color: palette.primary,
          backgroundColor: alpha(palette.primary, 0.10),
          borderColor: alpha(palette.primary, 0.40),
          boxShadow: `0 0 14px ${alpha(palette.primary, 0.12)}`,
        },
        colorSuccess: {
          color: palette.success,
          backgroundColor: alpha(palette.success, 0.10),
          borderColor: alpha(palette.success, 0.38),
        },
        colorError: {
          color: '#FF6B81',
          backgroundColor: alpha(palette.danger, 0.10),
          borderColor: alpha(palette.danger, 0.40),
          boxShadow: `0 0 14px ${alpha(palette.danger, 0.12)}`,
        },
        colorWarning: {
          color: '#FFC857',
          backgroundColor: alpha(palette.warning, 0.10),
          borderColor: alpha(palette.warning, 0.38),
        },
        colorInfo: {
          color: palette.info,
          backgroundColor: alpha(palette.info, 0.10),
          borderColor: alpha(palette.info, 0.38),
        },
      },
    },
    MuiTableContainer: { styleOverrides: { root: { borderRadius: 16 } } },
    MuiTableCell: {
      styleOverrides: {
        root: { borderBottom: '1px solid rgba(255,255,255,0.055)', paddingBlock: 13 },
        head: {
          fontWeight: 800,
          fontSize: '0.72rem',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: palette.muted,
          backgroundColor: 'rgba(10,15,28,0.72)',
          backdropFilter: 'blur(12px)',
          borderBottom: `1px solid ${alpha(palette.primary, 0.16)}`,
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          transition: 'background 160ms ease',
          '&:hover': {
            backgroundColor: alpha(palette.primary, 0.05),
            '& td': { borderBottomColor: alpha(palette.primary, 0.20) },
          },
        },
      },
    },
    MuiTextField: { defaultProps: { variant: 'outlined' } },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          backgroundColor: 'rgba(10,15,28,0.55)',
          transition: 'box-shadow 180ms ease, border-color 180ms ease',
          '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.12)' },
          '&:hover .MuiOutlinedInput-notchedOutline': {
            borderColor: alpha(palette.primary, 0.40),
          },
          '&.Mui-focused': {
            boxShadow: `0 0 0 3px ${alpha(palette.primary, 0.12)}, 0 0 24px ${alpha(palette.primary, 0.12)}`,
          },
          '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: palette.primary },
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: { root: { color: palette.muted } },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: 'rgba(10,15,28,0.72)',
          backdropFilter: 'blur(18px)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          boxShadow: '0 12px 40px rgba(0,0,0,0.35)',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: 'rgba(10,15,28,0.86)',
          backdropFilter: 'blur(20px)',
          borderLeft: '1px solid rgba(255,255,255,0.08)',
          backgroundImage:
            'radial-gradient(circle at 100% 0%, rgba(112,0,255,0.16), transparent 42%), radial-gradient(circle at 0% 100%, rgba(0,240,255,0.10), transparent 40%)',
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          marginBottom: 4,
          color: palette.muted,
          transition: 'all 180ms ease',
          '&:hover': {
            backgroundColor: 'rgba(0,240,255,0.06)',
            color: palette.text,
          },
          '&.Mui-selected': {
            color: palette.primary,
            backgroundColor: 'rgba(0,240,255,0.10)',
            boxShadow: `inset 0 0 0 1px ${alpha(palette.primary, 0.22)}, 0 0 24px ${alpha(palette.primary, 0.10)}`,
            '& .MuiListItemIcon-root': { color: palette.primary },
          },
        },
      },
    },
    MuiListItemIcon: { styleOverrides: { root: { color: 'inherit', minWidth: 42 } } },
    MuiDialog: {
      styleOverrides: {
        paper: {
          background: 'linear-gradient(160deg, rgba(24,35,57,0.98), rgba(11,17,30,0.98))',
          border: `1px solid ${alpha(palette.primary, 0.18)}`,
          boxShadow: `0 40px 120px rgba(0,0,0,0.65), 0 0 40px ${alpha(palette.primary, 0.10)}`,
        },
      },
    },
    MuiBackdrop: {
      styleOverrides: { root: { backgroundColor: 'rgba(3,7,14,0.72)', backdropFilter: 'blur(6px)' } },
    },
    MuiMenu: {
      styleOverrides: {
        paper: {
          marginTop: 8,
          border: `1px solid ${alpha(palette.primary, 0.18)}`,
          boxShadow: `0 24px 60px rgba(0,0,0,0.55), 0 0 24px ${alpha(palette.primary, 0.08)}`,
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: 'rgba(11,18,32,0.96)',
          border: '1px solid rgba(255,255,255,0.10)',
          boxShadow: '0 12px 30px rgba(0,0,0,0.45)',
          fontSize: '0.75rem',
          lineHeight: 1.6,
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: { height: 3, borderRadius: 99, background: `linear-gradient(90deg, ${palette.primary}, ${palette.secondary})` },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontWeight: 700,
          '&.Mui-selected': { color: palette.primary },
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { height: 8, borderRadius: 99, backgroundColor: 'rgba(255,255,255,0.06)' },
        bar: { borderRadius: 99, background: `linear-gradient(90deg, ${palette.primary}, ${palette.secondary})` },
      },
    },
    MuiCircularProgress: {
      styleOverrides: { circle: { strokeLinecap: 'round' } },
    },
    MuiStepIcon: {
      styleOverrides: {
        root: {
          color: 'rgba(255,255,255,0.12)',
          '&.Mui-active': {
            color: palette.primary,
            filter: `drop-shadow(0 0 10px ${alpha(palette.primary, 0.65)})`,
          },
          '&.Mui-completed': {
            color: palette.success,
            filter: `drop-shadow(0 0 10px ${alpha(palette.success, 0.45)})`,
          },
        },
      },
    },
    MuiStepLabel: {
      styleOverrides: {
        label: { fontWeight: 700, '&.Mui-active': { color: palette.primary } },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 14,
          border: '1px solid rgba(255,255,255,0.08)',
          backdropFilter: 'blur(10px)',
        },
      },
    },
    MuiAvatar: {
      styleOverrides: {
        root: {
          background: `linear-gradient(135deg, ${palette.secondary}, ${palette.primary})`,
          color: '#fff',
          fontWeight: 800,
        },
      },
    },
    MuiSwitch: {
      styleOverrides: {
        thumb: { boxShadow: `0 0 12px ${alpha(palette.primary, 0.6)}` },
      },
    },
    MuiDivider: { styleOverrides: { root: { borderColor: 'rgba(255,255,255,0.08)' } } },
    MuiSkeleton: {
      styleOverrides: {
        root: { backgroundColor: 'rgba(255,255,255,0.06)' },
      },
    },
  },
});

export { shadow as neonShadow };
