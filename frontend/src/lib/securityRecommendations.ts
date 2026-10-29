/**
 * Curated security recommendations shown in the Dashboard's Security
 * Recommendations tab.  The long-form playbook lives at the repository root
 * (`DEFENSIVE_PLAYBOOK.md`); this file is the short, actionable layer.
 */
export type RecommendationCategory = 'hardening' | 'detection' | 'response' | 'awareness';
export type RecommendationSeverity = 'critical' | 'high' | 'medium';

export interface SecurityRecommendation {
  id: string;
  title: string;
  category: RecommendationCategory;
  severity: RecommendationSeverity;
  summary: string;
  implementation: string;
  reference: string;
}

export const RECOMMENDATION_CATEGORIES: Array<{
  id: RecommendationCategory | 'all';
  label: string;
}> = [
  { id: 'all', label: 'كل التوصيات' },
  { id: 'hardening', label: 'التحصين' },
  { id: 'detection', label: 'الكشف' },
  { id: 'response', label: 'الاستجابة' },
  { id: 'awareness', label: 'التوعية' },
];

export const CATEGORY_LABELS: Record<RecommendationCategory, string> = {
  hardening: 'التحصين',
  detection: 'الكشف',
  response: 'الاستجابة',
  awareness: 'التوعية',
};

export const SEVERITY_LABELS: Record<RecommendationSeverity, string> = {
  critical: 'حرج',
  high: 'مرتفع',
  medium: 'متوسط',
};

export const SECURITY_RECOMMENDATIONS: SecurityRecommendation[] = [
  {
    id: 'usb-device-control',
    title: 'حظر وسائط USB غير المصرّح بها',
    category: 'hardening',
    severity: 'critical',
    summary:
      'معظم حوادث الفلاشات تبدأ بجهاز غير مُدار أو وسيط غير موثوق. اسمح فقط بالفلاشات المشفّرة المملوكة للشركة، واحظر التخزين العام لبقية المستخدمين.',
    implementation:
      'Intune: Endpoint security → Attack surface reduction → Device control.\nGPO: Computer Configuration → Administrative Templates → System → Device Installation → Device Installation Restrictions → Prevent installation of removable devices = Enabled.\nراجع الاستثناءات ربع سنوياً واجعلها مؤقتة.',
    reference: 'DEFENSIVE_PLAYBOOK.md §3.2',
  },
  {
    id: 'asr-usb',
    title: 'تفعيل ASR لمنع التنفيذ من USB',
    category: 'hardening',
    severity: 'critical',
    summary:
      'قاعدة Attack Surface Reduction تمنع تشغيل الملفات غير الموثوقة من وسائط USB حتى لو ضغط الموظف على الملف. ابدأ بوضع Audit ثم انتقل إلى Block.',
    implementation:
      'Rule GUID: B2B3F03D-6A65-4F7B-A9C7-1C7EF74A9BA4\nPowerShell: Add-MpPreference -AttackSurfaceReductionRules_Ids B2B3F03D-6A65-4F7B-A9C7-1C7EF74A9BA4 -AttackSurfaceReductionRules_Actions Enabled\nتحقق: Get-MpPreference | Select AttackSurfaceReductionRules_*',
    reference: 'DEFENSIVE_PLAYBOOK.md §3.1',
  },
  {
    id: 'disable-autorun',
    title: 'تعطيل AutoPlay وAutoRun لكل الأقراص',
    category: 'hardening',
    severity: 'high',
    summary:
      'يمنع تشغيل أي محتوى تلقائياً عند توصيل الفلاشة، ويزيل واحدة من أقدم طرق الانتشار عبر الوسائط القابلة للإزالة.',
    implementation:
      'GPO: Computer Configuration → Administrative Templates → Windows Components → AutoPlay Policies → Turn off Autoplay = Enabled (All drives).\nIntune: Administrative Templates → Windows Components → AutoPlay Policies.\nتحقق من عدم وجود استثناءات قديمة في السجل.',
    reference: 'DEFENSIVE_PLAYBOOK.md §3.4',
  },
  {
    id: 'usb-telemetry',
    title: 'مراقبة توصيل USB وأحداث الملفات',
    category: 'detection',
    severity: 'high',
    summary:
      'بدون تسجيل التوصيل والملفات المنشأة على القرص، يبقى التحقيق أعمى. اجمع DriverFrameworks وSysmon Event ID 11 وMDE DeviceEvents.',
    implementation:
      'Sysmon: Event IDs 1 (process), 3 (network), 11 (file create), 13 (registry), 22 (DNS).\nWindows: Microsoft-Windows-DriverFrameworks-UserMode/Operational 2003/2004.\nMDE: DeviceEvents | where ActionType has "Usb".\nاحتفظ بالسجلات 90 يوماً على الأقل.',
    reference: 'DEFENSIVE_PLAYBOOK.md §1.1, §1.5',
  },
  {
    id: 'double-extension',
    title: 'كشف الملفات ذات الامتداد المزدوج',
    category: 'detection',
    severity: 'high',
    summary:
      'ملف مثل راتب.pdf.exe يخدع المستخدم لأن Windows يخفي الامتداد المعروف. أنشئ تنبيهاً عند إنشاء الملف، لا عند تنفيذه فقط.',
    implementation:
      'KQL: DeviceFileEvents | where FileName matches regex @"(?i)\\.(pdf|docx?|xlsx?|pptx?)\\.(exe|scr|bat|cmd|js|vbs|lnk)$"\nأرسل التنبيه إلى SOC مع اسم الجهاز والمستخدم والمسار، واطلب من المستخدم عدم فتح الملف.',
    reference: 'DEFENSIVE_PLAYBOOK.md §1.3, §1.7',
  },
  {
    id: 'beaconing',
    title: 'كشف اتصالات C2 الدورية (Beaconing)',
    category: 'detection',
    severity: 'high',
    summary:
      'بعد تنفيذ ملف من USB، غالباً يبدأ اتصال دوري بخادم تحكم. ابحث عن وجهات عامة نادرة، ومنافذ غير قياسية، وعملية ثابتة تكرر الاتصال.',
    implementation:
      'KQL: جمّع DeviceNetworkEvents حسب DeviceName وRemoteIP، ثم احسب عدد الاتصالات والمدة ومتوسط الفاصل الزمني. راجع الوجهات التي تظهر على جهاز أو جهازين فقط.\nأثرِ النتائج بـ VirusTotal/GreyNoise قبل الحظر.',
    reference: 'DEFENSIVE_PLAYBOOK.md §1.8, §1.9',
  },
  {
    id: 'usb-ir',
    title: 'خطة استجابة جاهزة لحادث USB',
    category: 'response',
    severity: 'high',
    summary:
      'عزل الجهاز، حفظ الدليل، تحديد الملف والبصمة، ثم إزالة الثبات وإعادة التهيئة عند الشك. لا تطلب من الموظف تشغيل الملف مرة أخرى.',
    implementation:
      '1) عزل عبر EDR (وليس إيقاف تشغيل).\n2) سجّل اسم الملف وSHA-256 والجهاز والمستخدم.\n3) احظر البصمة وC2.\n4) أعد تعيين بيانات الدخول إن تأكد التنفيذ.\n5) أعد التهيئة عند غياب اليقين.\n6) راقب 72 ساعة بعد الاستعادة.',
    reference: 'DEFENSIVE_PLAYBOOK.md §2',
  },
  {
    id: 'usb-awareness',
    title: 'تمرين إسقاط USB آمن ومقاس',
    category: 'awareness',
    severity: 'medium',
    summary:
      'اختبر سلوك الموظفين بملف PDF خامل فقط، وقس نسبة التوصيل والفتح والإبلاغ. التمرين لا يستخدم أي برنامج أو أمر تنفيذي ولا يعاقب الأفراد.',
    implementation:
      'استخدم README_USB.md لإنشاء الحملة وتنزيل الملف وتوزيعه.\nكل صفحة تحمل QR فريداً؛ أول فتح يسجل usb_opened ويخصم 25 Elo.\nاجمع: عدد الفلاشات، عدد التوصيل، عدد الفتح، عدد الإبلاغ، وزمن الإبلاغ.\nشارك النتائج بشكل مجمّع وغير لومي.',
    reference: 'README_USB.md',
  },
];
