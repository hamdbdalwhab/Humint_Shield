/**
 * Application shell — the "command centre" chrome.
 *
 * A permanent, glassy Arabic-first sidebar, a live notification bell fed by
 * real ledger events, and cinematic route transitions. The layout is RTL by
 * default and collapses to a temporary drawer on small screens.
 */
import AppBar from '@mui/material/AppBar';
import Avatar from '@mui/material/Avatar';
import Badge from '@mui/material/Badge';
import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import Drawer from '@mui/material/Drawer';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Popover from '@mui/material/Popover';
import Stack from '@mui/material/Stack';
import Toolbar from '@mui/material/Toolbar';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { alpha, useTheme } from '@mui/material/styles';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  ChevronLeft,
  ClipboardList,
  GraduationCap,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Mail,
  Megaphone,
  Menu as MenuIcon,
  MousePointerClick,
  ScanEye,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Terminal,
  Usb,
  Users,
} from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { lmsApi } from '@/api/endpoints';
import { PageTransition } from '@/components/PageTransition';
import { useAuth } from '@/hooks/useAuth';
import { relativeArabic } from '@/lib/format';

const DRAWER_WIDTH = 276;
const HEADER_HEIGHT = 74;

interface NavItem {
  labelAr: string;
  labelEn: string;
  to: string;
  icon: ReactNode;
}

const CAMPAIGN_NAV: NavItem[] = [
  { labelAr: 'مركز القيادة', labelEn: 'Command Center', to: '/', icon: <LayoutDashboard size={19} /> },
  { labelAr: 'الموظفون', labelEn: 'Human Assets', to: '/employees', icon: <Users size={19} /> },
  { labelAr: 'قوالب الرسائل', labelEn: 'Templates', to: '/templates', icon: <Mail size={19} /> },
  { labelAr: 'الحملات', labelEn: 'Campaigns', to: '/campaigns', icon: <Megaphone size={19} /> },
  { labelAr: 'التقارير', labelEn: 'Reports', to: '/reports', icon: <BarChart3 size={19} /> },
  { labelAr: 'محاكاة SOC', labelEn: 'SOC Simulation', to: '/incident-response-simulation', icon: <Terminal size={19} /> },
];

const LMS_NAV: NavItem[] = [
  { labelAr: 'مكتبة التدريب', labelEn: 'Training Library', to: '/training-library', icon: <BookOpen size={19} /> },
  { labelAr: 'المهام التدريبية', labelEn: 'Assignments', to: '/assignments', icon: <ClipboardList size={19} /> },
  { labelAr: 'تدريبي', labelEn: 'My Training', to: '/my-training', icon: <GraduationCap size={19} /> },
  { labelAr: 'صندوق البلاغات', labelEn: 'Report Inbox', to: '/report-inbox', icon: <Inbox size={19} /> },
  { labelAr: 'الإعدادات', labelEn: 'Settings', to: '/settings', icon: <Settings size={19} /> },
];

const PAGE_TITLES: Array<{ prefix: string; ar: string; en: string }> = [
  { prefix: '/employees', ar: 'الموظفون', en: 'Human Assets' },
  { prefix: '/templates', ar: 'قوالب الرسائل', en: 'Templates' },
  { prefix: '/campaigns', ar: 'الحملات', en: 'Campaigns' },
  { prefix: '/reports', ar: 'التقارير', en: 'Reports' },
  {
    prefix: '/incident-response-simulation',
    ar: 'محاكاة SOC',
    en: 'SOC Simulation',
  },
  { prefix: '/training-library', ar: 'مكتبة التدريب', en: 'Training Library' },
  { prefix: '/assignments', ar: 'المهام التدريبية', en: 'Assignments' },
  { prefix: '/my-training', ar: 'تدريبي', en: 'My Training' },
  { prefix: '/report-inbox', ar: 'صندوق البلاغات', en: 'Report Inbox' },
  { prefix: '/settings', ar: 'الإعدادات', en: 'Settings' },
  { prefix: '/change-password', ar: 'تغيير كلمة المرور', en: 'Change Password' },
];

interface RecentEvent {
  id: string;
  employee_name: string;
  event_type: string;
  label: string;
  campaign_id: string;
  campaign_name: string;
  occurred_at: string | null;
}

function eventIcon(type: string): ReactNode {
  if (type.includes('usb')) return <Usb size={16} />;
  if (type.includes('submitted')) return <KeyRound size={16} />;
  if (type.includes('click')) return <MousePointerClick size={16} />;
  if (type.includes('form_viewed')) return <ScanEye size={16} />;
  if (type.includes('reported') || type.includes('completed')) return <ShieldCheck size={16} />;
  if (type.includes('open')) return <Mail size={16} />;
  return <Activity size={16} />;
}

function eventColor(type: string): string {
  if (type.includes('usb')) return '#FF1744';
  if (type.includes('submitted')) return '#FF1744';
  if (type.includes('click') || type.includes('form_viewed')) return '#FFB020';
  if (type.includes('reported') || type.includes('completed')) return '#00E676';
  return '#00F0FF';
}

function BrandMark() {
  return (
    <Box
      sx={{
        width: 42,
        height: 42,
        borderRadius: 2.5,
        display: 'grid',
        placeItems: 'center',
        background: 'linear-gradient(135deg, rgba(0,240,255,.18), rgba(112,0,255,.28))',
        border: '1px solid rgba(0,240,255,.35)',
        boxShadow: '0 0 28px rgba(0,240,255,.22)',
        color: '#00F0FF',
        flex: '0 0 auto',
      }}
    >
      <Shield size={23} strokeWidth={2.2} />
    </Box>
  );
}

function NavGroup({
  items,
  title,
  onNavigate,
}: {
  items: NavItem[];
  title: string;
  onNavigate: () => void;
}) {
  const location = useLocation();
  return (
    <Box sx={{ mb: 2 }}>
      <Typography
        variant="overline"
        sx={{ px: 1.5, mb: 0.75, display: 'block', color: 'text.secondary', opacity: 0.75 }}
      >
        {title}
      </Typography>
      <List disablePadding>
        {items.map((item) => {
          const selected =
            item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to);
          return (
            <ListItemButton
              key={item.to}
              component={NavLink}
              to={item.to}
              selected={selected}
              onClick={onNavigate}
              sx={{ position: 'relative', py: 1.05, overflow: 'hidden' }}
            >
              {selected ? (
                <motion.span
                  layoutId="nav-active-glow"
                  transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                  style={{
                    position: 'absolute',
                    inset: 0,
                    borderRadius: 12,
                    background:
                      'linear-gradient(90deg, rgba(0,240,255,.14), rgba(112,0,255,.07))',
                    border: '1px solid rgba(0,240,255,.22)',
                    pointerEvents: 'none',
                  }}
                />
              ) : null}
              <ListItemIcon sx={{ position: 'relative', zIndex: 1 }}>{item.icon}</ListItemIcon>
              <ListItemText
                sx={{ position: 'relative', zIndex: 1, my: 0 }}
                primary={item.labelAr}
                secondary={item.labelEn}
                primaryTypographyProps={{ fontWeight: 700, fontSize: '0.9rem', lineHeight: 1.4 }}
                secondaryTypographyProps={{
                  fontSize: '0.66rem',
                  color: 'text.secondary',
                  letterSpacing: '0.04em',
                }}
              />
              {selected ? (
                <ChevronLeft size={15} style={{ opacity: 0.7, position: 'relative', zIndex: 1 }} />
              ) : null}
            </ListItemButton>
          );
        })}
      </List>
    </Box>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [profileAnchor, setProfileAnchor] = useState<null | HTMLElement>(null);
  const [bellAnchor, setBellAnchor] = useState<null | HTMLElement>(null);
  const { user, logout, organizationId } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const theme = useTheme();

  const dashboardQuery = useQuery({
    queryKey: ['dashboard', organizationId],
    queryFn: () => lmsApi.dashboard(organizationId as string),
    enabled: Boolean(organizationId),
    refetchInterval: 20_000,
    staleTime: 8_000,
  });

  const events = useMemo(
    () => ((dashboardQuery.data?.recent_events ?? []) as RecentEvent[]).slice(0, 8),
    [dashboardQuery.data],
  );

  const pageTitle = useMemo(() => {
    if (location.pathname === '/') return { ar: 'مركز القيادة', en: 'Command Center' };
    const match = PAGE_TITLES.find((item) => location.pathname.startsWith(item.prefix));
    return match ?? { ar: 'HUMINT Shield', en: 'Security Platform' };
  }, [location.pathname]);

  const initials = (user?.username ?? 'HS').slice(0, 2).toUpperCase();
  const newestEvent = events[0];

  const drawerContent = (
    <Box
      role="navigation"
      aria-label="التنقل الرئيسي"
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        px: 1.5,
        pb: 2,
        pt: 1.5,
      }}
    >
      <Stack direction="row" spacing={1.4} alignItems="center" sx={{ px: 1, py: 1.5, mb: 1 }}>
        <BrandMark />
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800, fontSize: '1rem', lineHeight: 1.2, letterSpacing: '-0.01em' }}>
            HUMINT <Box component="span" sx={{ color: 'primary.main' }}>Shield</Box>
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.64rem', letterSpacing: '.08em' }}>
            HUMAN RISK COMMAND
          </Typography>
        </Box>
      </Stack>

      <Divider sx={{ mb: 2 }} />

      <Box sx={{ flex: 1, overflowY: 'auto', pr: 0.25 }}>
        <NavGroup items={CAMPAIGN_NAV} title="العمليات الأمنية" onNavigate={() => setMobileOpen(false)} />
        <NavGroup items={LMS_NAV} title="التوعية والتعلم" onNavigate={() => setMobileOpen(false)} />
      </Box>

      <Box
        sx={{
          mt: 1,
          p: 1.5,
          borderRadius: 3,
          border: '1px solid rgba(0,240,255,.16)',
          background: 'linear-gradient(135deg, rgba(0,240,255,.07), rgba(112,0,255,.05))',
        }}
      >
        <Stack direction="row" spacing={1} alignItems="center">
          <Box
            className={dashboardQuery.isError ? 'mc-live-dot mc-danger-dot' : 'mc-live-dot'}
            sx={{ flex: '0 0 auto' }}
          />
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography sx={{ fontSize: '0.76rem', fontWeight: 700, lineHeight: 1.4 }}>
              {dashboardQuery.isError ? 'انقطاع في الاتصال' : 'المراقبة الحية تعمل'}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.64rem' }}>
              {newestEvent?.occurred_at
                ? `آخر حدث ${relativeArabic(newestEvent.occurred_at)}`
                : 'بانتظار أول حدث'}
            </Typography>
          </Box>
          <Sparkles size={15} color="#00F0FF" />
        </Stack>
      </Box>

      <Typography
        variant="caption"
        sx={{ textAlign: 'center', mt: 1.25, color: 'text.disabled', fontSize: '0.6rem', letterSpacing: '.1em' }}
      >
        V1.0 · MIDNIGHT CYBER
      </Typography>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', position: 'relative' }}>
      <Box className="mc-grid-overlay" />
      <Box className="mc-orb mc-orb--cyan" />
      <Box className="mc-orb mc-orb--violet" />

      <AppBar
        position="fixed"
        color="inherit"
        elevation={0}
        sx={{
          zIndex: theme.zIndex.drawer + 1,
          height: HEADER_HEIGHT,
          justifyContent: 'center',
          background: 'rgba(9,14,25,.72)',
          backdropFilter: 'blur(20px)',
        }}
      >
        <Toolbar sx={{ minHeight: `${HEADER_HEIGHT}px !important`, gap: 1.5, px: { xs: 1.5, md: 3 } }}>
          <IconButton
            edge="start"
            color="inherit"
            aria-label="فتح التنقل"
            onClick={() => setMobileOpen((open) => !open)}
            sx={{ display: { md: 'none' } }}
          >
            <MenuIcon size={21} />
          </IconButton>

          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography sx={{ fontWeight: 800, fontSize: { xs: '0.95rem', md: '1.06rem' }, lineHeight: 1.2 }}>
                {pageTitle.ar}
              </Typography>
              <Box
                sx={{
                  display: { xs: 'none', sm: 'inline-flex' },
                  px: 1,
                  py: 0.15,
                  borderRadius: 99,
                  bgcolor: 'rgba(0,240,255,.08)',
                  border: '1px solid rgba(0,240,255,.18)',
                }}
              >
                <Typography sx={{ fontSize: '0.6rem', color: 'primary.main', fontWeight: 700, letterSpacing: '.06em' }}>
                  {pageTitle.en.toUpperCase()}
                </Typography>
              </Box>
            </Stack>
            <Typography variant="caption" sx={{ color: 'text.secondary', display: { xs: 'none', sm: 'block' } }}>
              {new Date().toLocaleDateString('ar-JO', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
            </Typography>
          </Box>

          <Box sx={{ flex: 1 }} />

          <Tooltip title="واجهة عربية — RTL">
            <Box
              sx={{
                display: { xs: 'none', sm: 'flex' },
                alignItems: 'center',
                gap: 0.75,
                px: 1.2,
                py: 0.55,
                borderRadius: 99,
                border: '1px solid rgba(255,255,255,.10)',
                bgcolor: 'rgba(255,255,255,.03)',
                color: 'text.secondary',
              }}
            >
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 800, color: 'primary.main' }}>AR</Typography>
              <Typography sx={{ fontSize: '0.62rem' }}>RTL</Typography>
            </Box>
          </Tooltip>

          <Tooltip title="أحدث أحداث التتبع">
            <IconButton
              onClick={(event) => setBellAnchor(event.currentTarget)}
              aria-label="الإشعارات"
              sx={{ position: 'relative' }}
            >
              <Badge
                badgeContent={events.length}
                color="error"
                invisible={events.length === 0}
                sx={{ '& .MuiBadge-badge': { boxShadow: '0 0 12px rgba(255,23,68,.5)' } }}
              >
                <Bell size={20} />
              </Badge>
            </IconButton>
          </Tooltip>

          <Tooltip title={user ? `${user.email} (${user.role})` : ''}>
            <IconButton onClick={(event) => setProfileAnchor(event.currentTarget)} sx={{ p: 0.4 }}>
              <Badge
                overlap="circular"
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                variant="dot"
                sx={{ '& .MuiBadge-dot': { bgcolor: 'success.main', boxShadow: '0 0 10px #00E676' } }}
              >
                <Avatar
                  sx={{
                    width: 38,
                    height: 38,
                    fontSize: '0.8rem',
                    boxShadow: '0 0 0 2px rgba(0,240,255,.22), 0 0 24px rgba(0,240,255,.28)',
                  }}
                >
                  {initials}
                </Avatar>
              </Badge>
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      <Popover
        open={Boolean(bellAnchor)}
        anchorEl={bellAnchor}
        onClose={() => setBellAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { width: 380, maxWidth: '92vw', mt: 1, borderRadius: 3, overflow: 'hidden' } } }}
      >
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2, py: 1.5 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Activity size={17} color="#00F0FF" />
            <Typography sx={{ fontWeight: 800, fontSize: '0.9rem' }}>نبض الأحداث</Typography>
          </Stack>
          <Box className="mc-live-dot" />
        </Stack>
        <Divider />
        <Box sx={{ maxHeight: 380, overflowY: 'auto' }}>
          {events.length === 0 ? (
            <Box sx={{ p: 3, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                لا توجد أحداث تتبع بعد.
              </Typography>
            </Box>
          ) : (
            events.map((event) => {
              const color = eventColor(event.event_type);
              return (
                <Box
                  key={event.id}
                  onClick={() => {
                    setBellAnchor(null);
                    navigate(`/campaigns/${event.campaign_id}/live`);
                  }}
                  sx={{
                    display: 'flex',
                    gap: 1.25,
                    px: 2,
                    py: 1.2,
                    cursor: 'pointer',
                    borderBottom: '1px solid rgba(255,255,255,.05)',
                    '&:hover': { bgcolor: 'rgba(0,240,255,.05)' },
                  }}
                >
                  <Box
                    sx={{
                      width: 32,
                      height: 32,
                      borderRadius: 2,
                      display: 'grid',
                      placeItems: 'center',
                      color,
                      bgcolor: alpha(color, 0.10),
                      border: `1px solid ${alpha(color, 0.25)}`,
                      flex: '0 0 auto',
                    }}
                  >
                    {eventIcon(event.event_type)}
                  </Box>
                  <Box sx={{ minWidth: 0, flex: 1 }}>
                    <Typography sx={{ fontSize: '0.78rem', fontWeight: 700, lineHeight: 1.5 }}>
                      {event.employee_name}
                      <Box component="span" sx={{ color: 'text.secondary', fontWeight: 500 }}>
                        {' '}— {event.label}
                      </Box>
                    </Typography>
                    <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }} noWrap>
                      {event.campaign_name} · {event.occurred_at ? relativeArabic(event.occurred_at) : ''}
                    </Typography>
                  </Box>
                </Box>
              );
            })
          )}
        </Box>
        <Box
          onClick={() => {
            setBellAnchor(null);
            navigate('/campaigns');
          }}
          sx={{
            px: 2,
            py: 1.1,
            textAlign: 'center',
            cursor: 'pointer',
            color: 'primary.main',
            fontSize: '0.75rem',
            fontWeight: 700,
            borderTop: '1px solid rgba(255,255,255,.06)',
          }}
        >
          عرض كل الحملات
        </Box>
      </Popover>

      <Menu
        anchorEl={profileAnchor}
        open={Boolean(profileAnchor)}
        onClose={() => setProfileAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      >
        <MenuItem disabled sx={{ opacity: '1 !important' }}>
          <Stack spacing={0.2}>
            <Typography sx={{ fontWeight: 800, fontSize: '0.82rem' }}>{user?.username ?? 'مستخدم'}</Typography>
            <Typography variant="caption" color="text.secondary">
              {user?.email ?? ''} · {user?.role ?? ''}
            </Typography>
          </Stack>
        </MenuItem>
        <Divider />
        <MenuItem
          onClick={() => {
            setProfileAnchor(null);
            navigate('/change-password');
          }}
        >
          <ListItemIcon>
            <KeyRound size={16} />
          </ListItemIcon>
          <ListItemText primary="تغيير كلمة المرور" />
        </MenuItem>
        <MenuItem
          onClick={() => {
            setProfileAnchor(null);
            void logout();
          }}
        >
          <ListItemIcon>
            <LogOut size={16} />
          </ListItemIcon>
          <ListItemText primary="تسجيل الخروج" />
        </MenuItem>
      </Menu>

      <Box component="nav" sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }}>
        <Drawer
          variant="temporary"
          anchor="right"
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', md: 'none' },
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              pt: 1,
              insetInlineStart: 0,
              insetInlineEnd: 'auto',
            },
          }}
        >
          {drawerContent}
        </Drawer>
        <Drawer
          variant="permanent"
          anchor="right"
          sx={{
            display: { xs: 'none', md: 'block' },
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              top: HEADER_HEIGHT,
              height: `calc(100% - ${HEADER_HEIGHT}px)`,
              boxSizing: 'border-box',
              borderInlineEnd: '1px solid rgba(255,255,255,.08)',
              insetInlineStart: 0,
              insetInlineEnd: 'auto',
            },
          }}
          open
        >
          {drawerContent}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          minWidth: 0,
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          pt: `${HEADER_HEIGHT}px`,
          position: 'relative',
          zIndex: 1,
        }}
      >
        <Box sx={{ p: { xs: 1.6, sm: 2.2, md: 3 }, maxWidth: 1560, mx: 'auto' }}>
          <AnimatePresence mode="wait" initial={false}>
            <PageTransition key={location.pathname}>{children}</PageTransition>
          </AnimatePresence>
        </Box>
      </Box>
    </Box>
  );
}
