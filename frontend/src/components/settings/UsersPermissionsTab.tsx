/**
 * Operator administration: accounts, roles and a granular permission matrix.
 *
 * The matrix never duplicates the catalog: groups, labels and role presets come
 * from `GET /users/permissions`. A permission inherited from the role is shown
 * as locked; only the extra grants of the account are editable, which is what
 * the backend stores (least privilege by construction).
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import InputAdornment from '@mui/material/InputAdornment';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import SearchIcon from '@mui/icons-material/Search';
import { Lock, Plus, ShieldCheck, UserCog } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { usersApi } from '@/api/endpoints';
import { LoadingState } from '@/components/Feedback';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import type { PermissionCatalog, Role, UserAdmin } from '@/types';

const ROLE_COLOR: Record<Role, 'error' | 'warning' | 'info' | 'default'> = {
  admin: 'error',
  manager: 'warning',
  viewer: 'info',
  custom: 'default',
};

const PASSWORD_RULES: Array<{ label: string; test: (value: string) => boolean }> = [
  { label: '٨ أحرف على الأقل', test: (v) => v.length >= 8 },
  { label: 'حرف كبير', test: (v) => /[A-Z]/.test(v) },
  { label: 'حرف صغير', test: (v) => /[a-z]/.test(v) },
  { label: 'رقم', test: (v) => /[0-9]/.test(v) },
  { label: 'رمز خاص', test: (v) => /[^A-Za-z0-9]/.test(v) },
];

function passwordValid(value: string): boolean {
  return PASSWORD_RULES.every((rule) => rule.test(value));
}

function PasswordHints({ value }: { value: string }) {
  return (
    <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
      {PASSWORD_RULES.map((rule) => (
        <Chip
          key={rule.label}
          size="small"
          variant={rule.test(value) ? 'filled' : 'outlined'}
          color={rule.test(value) ? 'success' : 'default'}
          label={rule.label}
        />
      ))}
    </Stack>
  );
}

interface MatrixProps {
  catalog: PermissionCatalog;
  role: Role;
  grants: string[];
  onToggle: (permission: string) => void;
  disabled?: boolean;
}

/** Grouped permission matrix; role-inherited permissions are locked. */
function PermissionMatrix({ catalog, role, grants, onToggle, disabled }: MatrixProps) {
  const [query, setQuery] = useState('');
  const inherited = useMemo(() => {
    const preset = catalog.roles.find((item) => item.key === role)?.default_permissions ?? [];
    return new Set(preset);
  }, [catalog.roles, role]);

  const needle = query.trim().toLowerCase();
  const groups = useMemo(
    () =>
      catalog.groups
        .map((group) => ({
          ...group,
          visible: group.permissions.filter(
            (permission) =>
              !needle ||
              permission.key.toLowerCase().includes(needle) ||
              permission.label_ar.includes(query.trim()) ||
              permission.label_en.toLowerCase().includes(needle),
          ),
        }))
        .filter((group) => group.visible.length > 0),
    [catalog.groups, needle, query],
  );

  return (
    <Stack spacing={1.5}>
      <TextField
        size="small"
        fullWidth
        placeholder="ابحث عن صلاحية بالاسم أو المفتاح…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          ),
        }}
      />
      {groups.length === 0 ? (
        <Alert severity="info">لا توجد صلاحية مطابقة لـ «{query}».</Alert>
      ) : null}
      {groups.map((group) => {
        const granted = group.permissions.filter(
          (permission) => inherited.has(permission.key) || grants.includes(permission.key),
        ).length;
        return (
        <Box
          key={group.key}
          sx={{
            border: '1px solid rgba(255,255,255,.08)',
            borderRadius: 2,
            p: 1.5,
          }}
        >
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <Typography sx={{ fontWeight: 800, fontSize: '0.82rem' }}>
              {group.label_ar}
              <Box component="span" sx={{ color: 'text.secondary', fontWeight: 500, ml: 1, fontSize: '0.7rem' }}>
                {group.label_en}
              </Box>
            </Typography>
            <Box sx={{ flexGrow: 1 }} />
            <Chip
              size="small"
              variant="outlined"
              color={granted === group.permissions.length ? 'success' : 'default'}
              label={`${granted}/${group.permissions.length}`}
              sx={{ height: 20, fontSize: '0.68rem' }}
            />
          </Stack>
          <Stack direction="row" sx={{ flexWrap: 'wrap', columnGap: 2, rowGap: 0.25 }}>
            {group.visible.map((permission) => {
              const locked = inherited.has(permission.key);
              const checked = locked || grants.includes(permission.key);
              return (
                <Tooltip
                  key={permission.key}
                  title={
                    locked
                      ? 'ممنوحة تلقائياً بواسطة الدور — غيّر الدور أو استخدم دوراً مخصّصاً للتعديل'
                      : permission.label_en
                  }
                >
                  <FormControlLabel
                    sx={{ mr: 0, maxWidth: 260 }}
                    control={
                      <Checkbox
                        size="small"
                        checked={checked}
                        disabled={disabled || locked}
                        onChange={() => onToggle(permission.key)}
                        icon={locked ? <Lock size={16} /> : undefined}
                      />
                    }
                    label={
                      <Typography sx={{ fontSize: '0.78rem' }}>
                        {permission.label_ar}
                        {locked ? (
                          <Box component="span" sx={{ color: 'text.secondary', fontSize: '0.66rem', ml: 0.5 }}>
                            (من الدور)
                          </Box>
                        ) : null}
                      </Typography>
                    }
                  />
                </Tooltip>
              );
            })}
          </Stack>
        </Box>
        );
      })}
    </Stack>
  );
}

interface EditorState {
  username: string;
  email: string;
  password: string;
  role: Role;
  grants: string[];
  isActive: boolean;
}

const EMPTY_EDITOR: EditorState = {
  username: '',
  email: '',
  password: '',
  role: 'viewer',
  grants: [],
  isActive: true,
};

export function UsersPermissionsTab() {
  const { user: currentUser, can } = useAuth();
  const queryClient = useQueryClient();
  const canManage = can('users.manage');
  const canView = can('users.view') || canManage;

  const catalogQuery = useQuery({
    queryKey: ['permission-catalog'],
    queryFn: () => usersApi.permissions(),
    enabled: canView,
    staleTime: 300_000,
  });
  const usersQuery = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.list(),
    enabled: canView,
  });

  const [createOpen, setCreateOpen] = useState(false);
  const [createState, setCreateState] = useState<EditorState>(EMPTY_EDITOR);
  const [editing, setEditing] = useState<UserAdmin | null>(null);
  const [editState, setEditState] = useState<EditorState>(EMPTY_EDITOR);
  const [resetPassword, setResetPassword] = useState('');

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['users'] });

  const createMutation = useMutation({
    mutationFn: () =>
      usersApi.create({
        username: createState.username.trim(),
        email: createState.email.trim(),
        password: createState.password,
        role: createState.role,
        permissions: createState.grants,
      }),
    onSuccess: (created) => {
      toast.success(`تم إنشاء الحساب «${created.username}»`);
      setCreateOpen(false);
      setCreateState(EMPTY_EDITOR);
      void refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      usersApi.update(editing?.id ?? '', {
        email: editState.email.trim(),
        role: editState.role,
        permissions: editState.grants,
        is_active: editState.isActive,
      }),
    onSuccess: () => {
      toast.success('تم تحديث الحساب والصلاحيات');
      setEditing(null);
      void refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const resetMutation = useMutation({
    mutationFn: () => usersApi.resetPassword(editing?.id ?? '', resetPassword),
    onSuccess: () => {
      toast.success('تم تعيين كلمة مرور جديدة وإبطال الجلسات القديمة');
      setResetPassword('');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => usersApi.deactivate(id),
    onSuccess: () => {
      toast.success('تم تعطيل الحساب');
      setEditing(null);
      void refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const catalog = catalogQuery.data;
  const users = usersQuery.data ?? [];
  const activeCount = users.filter((item) => item.is_active).length;

  const allKeys = catalog?.groups.flatMap((group) => group.permissions.map((item) => item.key)) ?? [];
  const viewKeys = allKeys.filter((key) => key.endsWith('.view'));
  const operatorKeys = allKeys.filter(
    (key) =>
      !key.endsWith('.delete') && key !== 'users.manage' && key !== 'settings.branding',
  );

  /** Replace the extra grants with a named least-privilege bundle. */
  const applyGrants = (keys: string[]) => {
    const update = (state: EditorState): EditorState => ({ ...state, grants: keys });
    if (editing) setEditState(update);
    else setCreateState(update);
  };

  const openEdit = (target: UserAdmin) => {
    setEditing(target);
    setEditState({
      username: target.username,
      email: target.email,
      password: '',
      role: target.role,
      grants: target.permissions ?? [],
      isActive: target.is_active,
    });
    setResetPassword('');
  };

  const toggleGrant = (key: string) => {
    const update = (state: EditorState): EditorState => ({
      ...state,
      grants: state.grants.includes(key)
        ? state.grants.filter((item) => item !== key)
        : [...state.grants, key],
    });
    if (editing) setEditState(update);
    else setCreateState(update);
  };

  if (!canView) {
    return (
      <Alert severity="warning" icon={<ShieldCheck size={18} />}>
        إدارة المستخدمين تتطلب صلاحية users.view على الأقل. راجع مدير النظام لمنحك الوصول.
      </Alert>
    );
  }
  if (catalogQuery.isLoading || usersQuery.isLoading) {
    return <LoadingState label="جارٍ تحميل الحسابات ومصفوفة الصلاحيات…" />;
  }
  if (catalogQuery.error) return <Alert severity="error">{errorMessage(catalogQuery.error)}</Alert>;
  if (usersQuery.error) return <Alert severity="error">{errorMessage(usersQuery.error)}</Alert>;
  if (!catalog) return null;

  return (
    <Stack spacing={2}>
      <Alert severity={canManage ? 'info' : 'warning'} icon={<ShieldCheck size={18} />}>
        {canManage
          ? 'كل حساب يحصل على صلاحيات الدور تلقائياً، وأي منح إضافي يُسجّل ويُبطل جلسات الحساب القائمة فوراً. امنح أقل ما يلزم فقط.'
          : 'لديك صلاحية العرض فقط. إدارة الحسابات تتطلب صلاحية users.manage.'}
      </Alert>

      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        <Card sx={{ flex: '1 1 200px' }}>
          <CardContent>
            <Typography variant="caption" color="text.secondary">
              إجمالي الحسابات
            </Typography>
            <Typography sx={{ fontSize: '1.6rem', fontWeight: 900 }}>{users.length}</Typography>
          </CardContent>
        </Card>
        <Card sx={{ flex: '1 1 200px' }}>
          <CardContent>
            <Typography variant="caption" color="text.secondary">
              حسابات نشطة
            </Typography>
            <Typography sx={{ fontSize: '1.6rem', fontWeight: 900, color: 'success.main' }}>
              {activeCount}
            </Typography>
          </CardContent>
        </Card>
        <Card sx={{ flex: '1 1 200px' }}>
          <CardContent>
            <Typography variant="caption" color="text.secondary">
              صلاحيات متاحة
            </Typography>
            <Typography sx={{ fontSize: '1.6rem', fontWeight: 900, color: 'primary.main' }}>
              {catalog.total_permissions}
            </Typography>
          </CardContent>
        </Card>
        <Box sx={{ flex: '2 1 320px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
          <Button
            variant="contained"
            startIcon={<Plus size={17} />}
            disabled={!canManage}
            onClick={() => {
              setCreateState(EMPTY_EDITOR);
              setCreateOpen(true);
            }}
          >
            إنشاء مستخدم
          </Button>
        </Box>
      </Box>

      <Card>
        <CardContent sx={{ pb: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <UserCog size={18} />
            <Typography variant="h3" sx={{ fontSize: '1.02rem' }}>
              حسابات المنصة
            </Typography>
          </Stack>
        </CardContent>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>المستخدم</TableCell>
                <TableCell>البريد الإلكتروني</TableCell>
                <TableCell>الدور</TableCell>
                <TableCell>الصلاحيات</TableCell>
                <TableCell>آخر دخول</TableCell>
                <TableCell>الحالة</TableCell>
                <TableCell align="left">إجراءات</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 3, color: 'text.secondary' }}>
                    لا توجد حسابات بعد.
                  </TableCell>
                </TableRow>
              ) : (
                users.map((row) => (
                  <TableRow key={row.id} hover>
                    <TableCell>
                      <Typography sx={{ fontWeight: 700, fontSize: '0.82rem' }}>
                        {row.username}
                        {row.id === currentUser?.id ? (
                          <Chip size="small" label="أنت" sx={{ ml: 1, height: 18 }} />
                        ) : null}
                      </Typography>
                    </TableCell>
                    <TableCell sx={{ fontSize: '0.78rem' }}>{row.email}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={ROLE_COLOR[row.role]}
                        label={catalog.roles.find((item) => item.key === row.role)?.label_ar ?? row.role}
                      />
                    </TableCell>
                    <TableCell>
                      <Tooltip
                        title={(row.effective_permissions ?? []).join(' · ') || 'لا صلاحيات'}
                      >
                        <Chip
                          size="small"
                          variant="outlined"
                          label={`${row.effective_permissions?.length ?? 0} صلاحية`}
                        />
                      </Tooltip>
                    </TableCell>
                    <TableCell sx={{ fontSize: '0.74rem', color: 'text.secondary' }}>
                      {row.last_login_at
                        ? new Date(row.last_login_at).toLocaleString('ar-JO', {
                            dateStyle: 'short',
                            timeStyle: 'short',
                          })
                        : 'لم يسجّل الدخول'}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        variant={row.is_active ? 'filled' : 'outlined'}
                        color={row.is_active ? 'success' : 'default'}
                        label={row.is_active ? 'نشط' : 'معطّل'}
                      />
                    </TableCell>
                    <TableCell align="left">
                      <Button
                        size="small"
                        disabled={!canManage}
                        onClick={() => openEdit(row)}
                      >
                        إدارة
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>

      {/* Create */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>إنشاء مستخدم جديد</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                label="اسم المستخدم"
                fullWidth
                value={createState.username}
                onChange={(event) => setCreateState({ ...createState, username: event.target.value })}
                helperText="٣ أحرف على الأقل، بدون وسوم HTML."
              />
              <TextField
                label="البريد الإلكتروني"
                type="email"
                fullWidth
                value={createState.email}
                onChange={(event) => setCreateState({ ...createState, email: event.target.value })}
              />
            </Stack>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                label="كلمة المرور الأولية"
                type="password"
                fullWidth
                value={createState.password}
                onChange={(event) => setCreateState({ ...createState, password: event.target.value })}
              />
              <FormControl fullWidth>
                <InputLabel id="create-role">الدور</InputLabel>
                <Select
                  labelId="create-role"
                  label="الدور"
                  value={createState.role}
                  onChange={(event) =>
                    setCreateState({ ...createState, role: event.target.value as Role, grants: [] })
                  }
                >
                  {catalog.roles.map((role) => (
                    <MenuItem key={role.key} value={role.key}>
                      {role.label_ar} — {role.label_en}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
            <PasswordHints value={createState.password} />
            <Divider />
            <Box>
              <Typography sx={{ fontWeight: 800, fontSize: '0.85rem', mb: 0.5 }}>
                صلاحيات إضافية
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                الصلاحيات المعلّمة بـ«من الدور» تأتي تلقائياً. اختر «مخصّص» للتحكم الكامل بمبدأ أقل صلاحية.
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: 'wrap', gap: 1 }}>
                <Chip
                  size="small"
                  clickable
                  label="قراءة فقط"
                  variant="outlined"
                  onClick={() => applyGrants(viewKeys)}
                />
                <Chip
                  size="small"
                  clickable
                  label="مشغّل بلا حذف"
                  variant="outlined"
                  onClick={() => applyGrants(operatorKeys)}
                />
                <Chip
                  size="small"
                  clickable
                  label="مسح كل المنح"
                  color="warning"
                  variant="outlined"
                  onClick={() => applyGrants([])}
                />
                <Chip
                  size="small"
                  label={`${createState.grants.length} منح إضافي`}
                  color="primary"
                />
              </Stack>
              <PermissionMatrix
                catalog={catalog}
                role={createState.role}
                grants={createState.grants}
                onToggle={toggleGrant}
              />
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>إلغاء</Button>
          <Button
            variant="contained"
            disabled={
              createMutation.isPending ||
              createState.username.trim().length < 3 ||
              !createState.email.includes('@') ||
              !passwordValid(createState.password)
            }
            startIcon={createMutation.isPending ? <CircularProgress size={16} color="inherit" /> : null}
            onClick={() => createMutation.mutate()}
          >
            إنشاء الحساب
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit */}
      <Dialog open={Boolean(editing)} onClose={() => setEditing(null)} maxWidth="md" fullWidth>
        <DialogTitle>إدارة «{editing?.username}»</DialogTitle>
        <DialogContent dividers>
          {editing ? (
            <Stack spacing={2}>
              {editing.id === currentUser?.id ? (
                <Alert severity="warning">
                  هذا حسابك الحالي: لا يمكنك تغيير دورك أو تعطيل نفسك. استخدم صفحة تغيير كلمة المرور.
                </Alert>
              ) : null}
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField
                  label="البريد الإلكتروني"
                  type="email"
                  fullWidth
                  value={editState.email}
                  onChange={(event) => setEditState({ ...editState, email: event.target.value })}
                />
                <FormControl fullWidth disabled={editing.id === currentUser?.id}>
                  <InputLabel id="edit-role">الدور</InputLabel>
                  <Select
                    labelId="edit-role"
                    label="الدور"
                    value={editState.role}
                    onChange={(event) =>
                      setEditState({ ...editState, role: event.target.value as Role, grants: [] })
                    }
                  >
                    {catalog.roles.map((role) => (
                      <MenuItem key={role.key} value={role.key}>
                        {role.label_ar} — {role.label_en}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Stack>
              <FormControlLabel
                control={
                  <Switch
                    checked={editState.isActive}
                    disabled={editing.id === currentUser?.id}
                    onChange={(event) =>
                      setEditState({ ...editState, isActive: event.target.checked })
                    }
                  />
                }
                label="الحساب نشط"
              />
              <Divider />
              <Box>
                <Typography sx={{ fontWeight: 800, fontSize: '0.85rem', mb: 0.5 }}>
                  مصفوفة الصلاحيات
                </Typography>
                <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: 'wrap', gap: 1 }}>
                  <Chip
                    size="small"
                    clickable
                    label="قراءة فقط"
                    variant="outlined"
                    onClick={() => applyGrants(viewKeys)}
                  />
                  <Chip
                    size="small"
                    clickable
                    label="مشغّل بلا حذف"
                    variant="outlined"
                    onClick={() => applyGrants(operatorKeys)}
                  />
                  <Chip
                    size="small"
                    clickable
                    label="مسح كل المنح"
                    color="warning"
                    variant="outlined"
                    onClick={() => applyGrants([])}
                  />
                  <Chip
                    size="small"
                    label={`${editState.grants.length} منح إضافي`}
                    color="primary"
                  />
                </Stack>
                <PermissionMatrix
                  catalog={catalog}
                  role={editState.role}
                  grants={editState.grants}
                  onToggle={toggleGrant}
                />
              </Box>
              <Divider />
              <Box>
                <Typography sx={{ fontWeight: 800, fontSize: '0.85rem', mb: 1 }}>
                  إعادة تعيين كلمة المرور
                </Typography>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems="flex-start">
                  <Stack spacing={1} sx={{ flex: 1 }}>
                    <TextField
                      label="كلمة المرور الجديدة"
                      type="password"
                      fullWidth
                      value={resetPassword}
                      onChange={(event) => setResetPassword(event.target.value)}
                    />
                    <PasswordHints value={resetPassword} />
                  </Stack>
                  <Button
                    variant="outlined"
                    disabled={resetMutation.isPending || !passwordValid(resetPassword)}
                    onClick={() => resetMutation.mutate()}
                  >
                    تعيين وإبطال الجلسات
                  </Button>
                </Stack>
              </Box>
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions sx={{ justifyContent: 'space-between' }}>
          <Button
            color="error"
            disabled={
              !editing ||
              editing.id === currentUser?.id ||
              !editing.is_active ||
              deactivateMutation.isPending
            }
            onClick={() => {
              if (editing) deactivateMutation.mutate(editing.id);
            }}
          >
            تعطيل الحساب
          </Button>
          <Box>
            <Button onClick={() => setEditing(null)}>إلغاء</Button>
            <Button
              variant="contained"
              disabled={updateMutation.isPending || !editState.email.includes('@')}
              startIcon={updateMutation.isPending ? <CircularProgress size={16} color="inherit" /> : null}
              onClick={() => updateMutation.mutate()}
            >
              حفظ التغييرات
            </Button>
          </Box>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
