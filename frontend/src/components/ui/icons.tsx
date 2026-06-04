"use client";

/**
 * Compatibility wrapper: Phosphor Icons with Lucide-compatible API.
 */
import React from "react";
import {
  ActivityIcon as PhActivity,
  ArrowBendUpRightIcon as PhArrowBendUpRight,
  ArrowDownIcon as PhArrowDown,
  ArrowLeftIcon as PhArrowLeft,
  ArrowRightIcon as PhArrowRight,
  ArrowSquareOutIcon as PhArrowSquareOut,
  ArrowUpIcon as PhArrowUp,
  ArrowsClockwiseIcon as PhArrowsClockwise,
  BellSimpleIcon as PhBellSimple,
  BookIcon as PhBook,
  BookOpenIcon as PhBookOpen,
  BookOpenTextIcon as PhBookOpenText,
  BookmarkSimpleIcon as PhBookmarkSimple,
  BrainIcon as PhBrain,
  BugIcon as PhBug,
  CalendarBlankIcon as PhCalendarBlank,
  CalendarDotsIcon as PhCalendarDots,
  CaretDownIcon as PhCaretDown,
  CaretLeftIcon as PhCaretLeft,
  CaretRightIcon as PhCaretRight,
  CaretUpIcon as PhCaretUp,
  CaretUpDownIcon as PhCaretUpDown,
  ChartBarIcon as PhChartBar,
  ChatCircleDotsIcon as PhChatCircleDots,
  ChatCircleIcon as PhChatCircle,
  ChatCircleTextIcon as PhChatCircleText,
  ChatsIcon as PhChats,
  CheckCircleIcon as PhCheckCircle,
  CheckIcon as PhCheck,
  CircleIcon as PhCircle,
  ClipboardTextIcon as PhClipboardText,
  ClockCounterClockwiseIcon as PhClockCounterClockwise,
  ClockIcon as PhClock,
  CodeIcon as PhCode,
  CoinsIcon as PhCoins,
  CompassIcon as PhCompass,
  CopySimpleIcon as PhCopySimple,
  CreditCardIcon as PhCreditCard,
  CursorTextIcon as PhCursorText,
  DatabaseIcon as PhDatabase,
  DotIcon as PhDot,
  DotsSixIcon as PhDotsSix,
  DotsSixVerticalIcon as PhDotsSixVertical,
  DotsThreeIcon as PhDotsThree,
  DownloadSimpleIcon as PhDownloadSimple,
  EnvelopeSimpleIcon as PhEnvelopeSimple,
  EyeIcon as PhEye,
  FactoryIcon as PhFactory,
  FileArrowDownIcon as PhFileArrowDown,
  FileCodeIcon as PhFileCode,
  FileIcon as PhFile,
  FileMagnifyingGlassIcon as PhFileMagnifyingGlass,
  FileTextIcon as PhFileText,
  FileVideoIcon as PhFileVideo,
  FilesIcon as PhFiles,
  FloppyDiskIcon as PhFloppyDisk,
  FolderOpenIcon as PhFolderOpen,
  FunnelIcon as PhFunnel,
  GaugeIcon as PhGauge,
  GearIcon as PhGear,
  GitBranchIcon as PhGitBranch,
  GlobeHemisphereEastIcon as PhGlobeHemisphereEast,
  GraduationCapIcon as PhGraduationCap,
  GridFourIcon as PhGridFour,
  HeartIcon as PhHeart,
  HeartbeatIcon as PhHeartbeat,
  ImageIcon as PhImage,
  InfoIcon as PhInfo,
  KeyboardIcon as PhKeyboard,
  LayoutIcon as PhLayout,
  LightbulbIcon as PhLightbulb,
  LightningIcon as PhLightning,
  ListChecksIcon as PhListChecks,
  LockSimpleIcon as PhLockSimple,
  MagnifyingGlassIcon as PhMagnifyingGlass,
  MicrophoneIcon as PhMicrophone,
  MicroscopeIcon as PhMicroscope,
  MonitorIcon as PhMonitor,
  MoonIcon as PhMoon,
  NotePencilIcon as PhNotePencil,
  NotebookIcon as PhNotebook,
  PackageIcon as PhPackage,
  PaletteIcon as PhPalette,
  PaperPlaneTiltIcon as PhPaperPlaneTilt,
  PaperclipIcon as PhPaperclip,
  PencilLineIcon as PhPencilLine,
  PlayIcon as PhPlay,
  PlusCircleIcon as PhPlusCircle,
  PlusIcon as PhPlus,
  PlusSquareIcon as PhPlusSquare,
  PowerIcon as PhPower,
  QuestionIcon as PhQuestion,
  RobotIcon as PhRobot,
  RocketLaunchIcon as PhRocketLaunch,
  ShapesIcon as PhShapes,
  ShareNetworkIcon as PhShareNetwork,
  ShieldCheckIcon as PhShieldCheck,
  ShieldIcon as PhShield,
  ShieldWarningIcon as PhShieldWarning,
  ShoppingBagIcon as PhShoppingBag,
  SidebarSimpleIcon as PhSidebarSimple,
  SignOutIcon as PhSignOut,
  SparkleIcon as PhSparkle,
  SpinnerIcon as PhSpinner,
  SquareIcon as PhSquare,
  SquaresFourIcon as PhSquaresFour,
  StarIcon as PhStar,
  StorefrontIcon as PhStorefront,
  SunIcon as PhSun,
  TableIcon as PhTable,
  TagIcon as PhTag,
  TerminalWindowIcon as PhTerminalWindow,
  ThumbsDownIcon as PhThumbsDown,
  ThumbsUpIcon as PhThumbsUp,
  TimerIcon as PhTimer,
  TrashIcon as PhTrash,
  TrendDownIcon as PhTrendDown,
  TrendUpIcon as PhTrendUp,
  UploadSimpleIcon as PhUploadSimple,
  UserCircleIcon as PhUserCircle,
  UserIcon as PhUser,
  UsersIcon as PhUsers,
  VideoCameraIcon as PhVideoCamera,
  WarningCircleIcon as PhWarningCircle,
  WarningIcon as PhWarning,
  WrenchIcon as PhWrench,
  XCircleIcon as PhXCircle,
  XIcon as PhX,
} from "@phosphor-icons/react";
import type { Icon as PhIcon } from "@phosphor-icons/react";

import { cn } from "@/lib/utils";

type PhosphorIcon = React.ComponentType<{
  size?: number;
  weight?: "thin" | "light" | "regular" | "bold" | "fill" | "duotone";
  className?: string;
  color?: string;
  "aria-hidden"?: boolean | "true" | "false";
}>;

function sizeFromClassName(className?: string): number {
  const m = className?.match(/size-(\d+)/);
  return m ? Number(m[1]) * 4 : 16;
}

type WrapperProps = React.ComponentProps<"svg"> & { size?: number };

function wrap(Icon: PhosphorIcon) {
  // forwardRef for ForwardRefExoticComponent compatibility,
  // but ref is not forwarded to Phosphor (it doesn't accept refs in 2.x).
  const Wrapped = React.forwardRef<SVGSVGElement, WrapperProps>(
    ({ className, color, size, ...rest }, _ref) => {
      const resolvedSize = size ?? sizeFromClassName(className);
      const filtered = className
        ?.split(/\s+/)
        .filter((c) => !c.startsWith("size-"))
        .join(" ");
      return (
        <Icon
          size={resolvedSize}
          weight="regular"
          className={filtered ? cn(filtered, "shrink-0") : "shrink-0"}
          {...(color ? { color } : {})}
          {...(rest as Record<string, unknown>)}
        />
      );
    },
  );
  Wrapped.displayName = `Icon(${Icon.displayName || "?"})`;
  return Wrapped;
}

// ---- Icon exports (with Icon suffix) ----
export const ActivityIcon = wrap(PhActivity);
export const AlertCircleIcon = wrap(PhWarningCircle);
export const AlertTriangleIcon = wrap(PhWarning);
export const ArrowDownIcon = wrap(PhArrowDown);
export const ArrowLeftIcon = wrap(PhArrowLeft);
export const ArrowRightIcon = wrap(PhArrowRight);
export const ArrowUpIcon = wrap(PhArrowUp);
export const BarChart3Icon = wrap(PhChartBar);
export const BarChartIcon = wrap(PhChartBar);
export const BellIcon = wrap(PhBellSimple);
export const BookIcon = wrap(PhBook);
export const BookOpenIcon = wrap(PhBookOpen);
export const BookOpenTextIcon = wrap(PhBookOpenText);
export const BookmarkIcon = wrap(PhBookmarkSimple);
export const BotIcon = wrap(PhRobot);
export const BrainIcon = wrap(PhBrain);
export const BugIcon = wrap(PhBug);
export const CalendarDays = wrap(PhCalendarDots);
export const CalendarDaysIcon = wrap(PhCalendarDots);
export const CalendarIcon = wrap(PhCalendarBlank);
export const CheckCircle2 = wrap(PhCheckCircle);
export const CheckCircle2Icon = wrap(PhCheckCircle);
export const CheckCircleIcon = wrap(PhCheckCircle);
export const CheckIcon = wrap(PhCheck);
export const ChevronDownIcon = wrap(PhCaretDown);
export const ChevronLeftIcon = wrap(PhCaretLeft);
export const ChevronRightIcon = wrap(PhCaretRight);
export const ChevronUpIcon = wrap(PhCaretUp);
export const ChevronsUpDownIcon = wrap(PhCaretUpDown);
export const CircleCheckIcon = wrap(PhCheckCircle);
export const CircleIcon = wrap(PhCircle);
export const ClipboardList = wrap(PhClipboardText);
export const ClipboardListIcon = wrap(PhClipboardText);
export const ClockIcon = wrap(PhClock);
export const Code2Icon = wrap(PhCode);
export const CoinsIcon = wrap(PhCoins);
export const CompassIcon = wrap(PhCompass);
export const CopyIcon = wrap(PhCopySimple);
export const CreditCardIcon = wrap(PhCreditCard);
export const DatabaseIcon = wrap(PhDatabase);
export const DotIcon = wrap(PhDot);
export const DownloadIcon = wrap(PhDownloadSimple);
export const ExternalLinkIcon = wrap(PhArrowSquareOut);
export const EyeIcon = wrap(PhEye);
export const FactoryIcon = wrap(PhFactory);
export const FileBarChartIcon = wrap(PhChartBar);
export const FileCodeIcon = wrap(PhFileCode);
export const FileCogIcon = wrap(PhGear);
export const FileDownIcon = wrap(PhFileArrowDown);
export const FileIcon = wrap(PhFile);
export const FileJsonIcon = wrap(PhFileText);
export const FilePlayIcon = wrap(PhFileVideo);
export const FileTextIcon = wrap(PhFileText);
export const FilesIcon = wrap(PhFiles);
export const FilterIcon = wrap(PhFunnel);
export const FolderOpenIcon = wrap(PhFolderOpen);
export const FormInputIcon = wrap(PhCursorText);
export const GaugeIcon = wrap(PhGauge);
export const GitBranchIcon = wrap(PhGitBranch);
export const GlobeIcon = wrap(PhGlobeHemisphereEast);
export const GraduationCapIcon = wrap(PhGraduationCap);
export const GripHorizontalIcon = wrap(PhDotsSix);
export const GripVerticalIcon = wrap(PhDotsSixVertical);
export const HeartIcon = wrap(PhHeart);
export const HeartPulseIcon = wrap(PhHeartbeat);
export const HistoryIcon = wrap(PhClockCounterClockwise);
export const ImageIcon = wrap(PhImage);
export const InfoIcon = wrap(PhInfo);
export const KeyboardIcon = wrap(PhKeyboard);
export const LayoutDashboardIcon = wrap(PhSquaresFour);
export const LayoutGridIcon = wrap(PhGridFour);
export const LightbulbIcon = wrap(PhLightbulb);
export const ListTodoIcon = wrap(PhListChecks);
export const Loader2Icon = wrap(PhSpinner);
export const LoaderIcon = wrap(PhSpinner);
export const LockIcon = wrap(PhLockSimple);
export const LogOutIcon = wrap(PhSignOut);
export const MailIcon = wrap(PhEnvelopeSimple);
export const MessageCircleIcon = wrap(PhChatCircle);
export const MessageCircleQuestionMarkIcon = wrap(PhQuestion);
export const MessageSquareIcon = wrap(PhChatCircleText);
export const MessageSquarePlusIcon = wrap(PhChatCircleDots);
export const MessagesSquareIcon = wrap(PhChats);
export const MicIcon = wrap(PhMicrophone);
export const MicroscopeIcon = wrap(PhMicroscope);
export const MonitorSmartphoneIcon = wrap(PhMonitor);
export const MoonIcon = wrap(PhMoon);
export const MoreHorizontalIcon = wrap(PhDotsThree);
export const NotebookPenIcon = wrap(PhNotebook);
export const OctagonXIcon = wrap(PhShieldCheck);
export const PackageIcon = wrap(PhPackage);
export const PaletteIcon = wrap(PhPalette);
export const PanelLeftCloseIcon = wrap(PhSidebarSimple);
export const PanelLeftOpenIcon = wrap(PhSidebarSimple);
export const PaperclipIcon = wrap(PhPaperclip);
export const PenLineIcon = wrap(PhPencilLine);
export const PencilIcon = wrap(PhNotePencil);
export const PlayIcon = wrap(PhPlay);
export const PlusIcon = wrap(PhPlus);
export const PlusSquareIcon = wrap(PhPlusSquare);
export const PowerIcon = wrap(PhPower);
export const RefreshCwIcon = wrap(PhArrowsClockwise);
export const RocketIcon = wrap(PhRocketLaunch);
export const SaveIcon = wrap(PhFloppyDisk);
export const SearchIcon = wrap(PhMagnifyingGlass);
export const SendIcon = wrap(PhPaperPlaneTilt);
export const Settings2Icon = wrap(PhGear);
export const SettingsIcon = wrap(PhGear);
export const ShapesIcon = wrap(PhShapes);
export const Share2Icon = wrap(PhShareNetwork);
export const ShieldAlertIcon = wrap(PhShieldWarning);
export const ShieldIcon = wrap(PhShield);
export const ShoppingBagIcon = wrap(PhShoppingBag);
export const SparklesIcon = wrap(PhSparkle);
export const SquareArrowOutUpRightIcon = wrap(PhArrowBendUpRight);
export const SquareIcon = wrap(PhSquare);
export const SquareTerminalIcon = wrap(PhTerminalWindow);
export const StarIcon = wrap(PhStar);
export const StoreIcon = wrap(PhStorefront);
export const SunIcon = wrap(PhSun);
export const Table2Icon = wrap(PhTable);
export const TagIcon = wrap(PhTag);
export const ThumbsDownIcon = wrap(PhThumbsDown);
export const ThumbsUpIcon = wrap(PhThumbsUp);
export const TimerIcon = wrap(PhTimer);
export const Trash2Icon = wrap(PhTrash);
export const TriangleAlertIcon = wrap(PhWarning);
export const TrendingDown = wrap(PhTrendDown);
export const TrendingUp = wrap(PhTrendUp);
export const UploadIcon = wrap(PhUploadSimple);
export const UserCircleIcon = wrap(PhUserCircle);
export const UserIcon = wrap(PhUser);
export const UsersIcon = wrap(PhUsers);
export const VideoIcon = wrap(PhVideoCamera);
export const WrenchIcon = wrap(PhWrench);
export const XCircleIcon = wrap(PhXCircle);
export const XIcon = wrap(PhX);
export const ZapIcon = wrap(PhLightning);

// ---- Non-suffixed aliases ----
export const Activity = wrap(PhActivity);
export const AlertCircle = wrap(PhWarningCircle);
export const AlertTriangle = wrap(PhWarning);
export const ArrowDown = wrap(PhArrowDown);
export const ArrowLeft = wrap(PhArrowLeft);
export const ArrowRight = wrap(PhArrowRight);
export const ArrowUp = wrap(PhArrowUp);
export const BarChart3 = wrap(PhChartBar);
export const Bell = wrap(PhBellSimple);
export const Calendar = wrap(PhCalendarBlank);
export const Check = wrap(PhCheck);
export const ChevronDown = wrap(PhCaretDown);
export const ChevronRight = wrap(PhCaretRight);
export const ChevronUp = wrap(PhCaretUp);
export const ChevronsUpDown = wrap(PhCaretUpDown);
export const Circle = wrap(PhCircle);
export const Clock = wrap(PhClock);
export const Code = wrap(PhCode);
export const CreditCard = wrap(PhCreditCard);
export const Database = wrap(PhDatabase);
export const Download = wrap(PhDownloadSimple);
export const Eye = wrap(PhEye);
export const Factory = wrap(PhFactory);
export const FileBarChart = wrap(PhChartBar);
export const FileDown = wrap(PhFileArrowDown);
export const FileJson = wrap(PhFileText);
export const FileText = wrap(PhFileText);
export const Filter = wrap(PhFunnel);
export const FormInput = wrap(PhCursorText);
export const GitBranch = wrap(PhGitBranch);
export const GripVertical = wrap(PhDotsSixVertical);
export const HeartPulse = wrap(PhHeartbeat);
export const Image = wrap(PhImage);
export const Info = wrap(PhInfo);
export const LayoutGrid = wrap(PhGridFour);
export const ListTodo = wrap(PhListChecks);
export const Loader2 = wrap(PhSpinner);
export const LogOut = wrap(PhSignOut);
export const MessageSquare = wrap(PhChatCircleText);
export const MessageSquarePlus = wrap(PhChatCircleDots);
export const MessagesSquare = wrap(PhChats);
export const MoreHorizontal = wrap(PhDotsThree);
export const Package = wrap(PhPackage);
export const PanelLeftClose = wrap(PhSidebarSimple);
export const PanelLeftOpen = wrap(PhSidebarSimple);
export const Pencil = wrap(PhNotePencil);
export const Play = wrap(PhPlay);
export const Plus = wrap(PhPlus);
export const PlusSquare = wrap(PhPlusSquare);
export const Power = wrap(PhPower);
export const RefreshCw = wrap(PhArrowsClockwise);
export const Save = wrap(PhFloppyDisk);
export const Search = wrap(PhMagnifyingGlass);
export const Send = wrap(PhPaperPlaneTilt);
export const Settings = wrap(PhGear);
export const Share2 = wrap(PhShareNetwork);
export const ShieldAlert = wrap(PhShieldWarning);
export const ShoppingBag = wrap(PhShoppingBag);
export const Star = wrap(PhStar);
export const Store = wrap(PhStorefront);
export const Table2 = wrap(PhTable);
export const Tag = wrap(PhTag);
export const Trash2 = wrap(PhTrash);
export const Wrench = wrap(PhWrench);
export const X = wrap(PhX);

export type LucideIcon = typeof ActivityIcon;
export type LucideProps = React.ComponentProps<typeof ActivityIcon>;
