/*
 * XFree86 vendor specific keysyms.
 *
 * The XFree86 keysym range is 0x10080001 - 0x1008ffff.
 *
 * The XF86 set of keysyms is a catch-all set of defines for keysyms found
 * on various multimedia keyboards. Originally specific to XFree86 they have
 * been been adopted over time and are considered a "standard" part of X
 * keysym definitions.
 * XFree86 never properly commented these keysyms, so we have done our
 * best to explain the semantic meaning of these keys.
 *
 * XFree86 has removed their mail archives of the period, that might have
 * shed more light on some of these definitions. Until/unless we resurrect
 * these archives, these are from memory and usage.
 */

/*
 * ModeLock
 *
 * This one is old, and not really used any more since XKB offers this
 * functionality.
 */

#define XF86XK_ModeLock              0x1008ff01  /* Mode Switch Lock */

/* Backlight controls. */
#define XF86XK_MonBrightnessUp       0x1008ff02  /* Monitor/panel brightness */
#define XF86XK_MonBrightnessDown     0x1008ff03  /* Monitor/panel brightness */
#define XF86XK_KbdLightOnOff         0x1008ff04  /* Keyboards may be lit     */
#define XF86XK_KbdBrightnessUp       0x1008ff05  /* Keyboards may be lit     */
#define XF86XK_KbdBrightnessDown     0x1008ff06  /* Keyboards may be lit     */
#define XF86XK_MonBrightnessCycle    0x1008ff07  /* Monitor/panel brightness */

/*
 * Keys found on some "Internet" keyboards.
 */
#define XF86XK_Standby               0x1008ff10  /* System into standby mode   */
#define XF86XK_AudioLowerVolume      0x1008ff11  /* Volume control down        */
#define XF86XK_AudioMute             0x1008ff12  /* Mute sound from the system */
#define XF86XK_AudioRaiseVolume      0x1008ff13  /* Volume control up          */
#define XF86XK_AudioPlay             0x1008ff14  /* Start playing of audio >   */
#define XF86XK_AudioStop             0x1008ff15  /* Stop playing audio         */
#define XF86XK_AudioPrev             0x1008ff16  /* Previous track             */
#define XF86XK_AudioNext             0x1008ff17  /* Next track                 */
#define XF86XK_HomePage              0x1008ff18  /* Display user's home page   */
#define XF86XK_Mail                  0x1008ff19  /* Invoke user's mail program */
#define XF86XK_Start                 0x1008ff1a  /* Start application          */
#define XF86XK_Search                0x1008ff1b  /* Search                     */
#define XF86XK_AudioRecord           0x1008ff1c  /* Record audio application   */

/* These are sometimes found on PDA's (e.g. Palm, PocketPC or elsewhere)   */
#define XF86XK_Calculator            0x1008ff1d  /* Invoke calculator program  */
#define XF86XK_Memo                  0x1008ff1e  /* Invoke Memo taking program */
#define XF86XK_ToDoList              0x1008ff1f  /* Invoke To Do List program  */
#define XF86XK_Calendar              0x1008ff20  /* Invoke Calendar program    */
#define XF86XK_PowerDown             0x1008ff21  /* Deep sleep the system      */
#define XF86XK_ContrastAdjust        0x1008ff22  /* Adjust screen contrast     */
#define XF86XK_RockerUp              0x1008ff23  /* Rocker switches exist up   */
#define XF86XK_RockerDown            0x1008ff24  /* and down                   */
#define XF86XK_RockerEnter           0x1008ff25  /* and let you press them     */

/* Some more "Internet" keyboard symbols */
#define XF86XK_Back                  0x1008ff26  /* Like back on a browser     */
#define XF86XK_Forward               0x1008ff27  /* Like forward on a browser  */
#define XF86XK_Stop                  0x1008ff28  /* Stop current operation     */
#define XF86XK_Refresh               0x1008ff29  /* Refresh the page           */
#define XF86XK_PowerOff              0x1008ff2a  /* Power off system entirely  */
#define XF86XK_WakeUp                0x1008ff2b  /* Wake up system from sleep  */
#define XF86XK_Eject                 0x1008ff2c  /* Eject device (e.g. DVD)    */
#define XF86XK_ScreenSaver           0x1008ff2d  /* Invoke screensaver         */
#define XF86XK_WWW                   0x1008ff2e  /* Invoke web browser         */
#define XF86XK_Sleep                 0x1008ff2f  /* Put system to sleep        */
#define XF86XK_Favorites             0x1008ff30  /* Show favorite locations    */
#define XF86XK_AudioPause            0x1008ff31  /* Pause audio playing        */
#define XF86XK_AudioMedia            0x1008ff32  /* Launch media collection app */
#define XF86XK_MyComputer            0x1008ff33  /* Display "My Computer" window */
#define XF86XK_VendorHome            0x1008ff34  /* Display vendor home web site */
#define XF86XK_LightBulb             0x1008ff35  /* Light bulb keys exist       */
#define XF86XK_Shop                  0x1008ff36  /* Display shopping web site   */
#define XF86XK_History               0x1008ff37  /* Show history of web surfing */
#define XF86XK_OpenURL               0x1008ff38  /* Open selected URL           */
#define XF86XK_AddFavorite           0x1008ff39  /* Add URL to favorites list   */
#define XF86XK_HotLinks              0x1008ff3a  /* Show "hot" links            */
#define XF86XK_BrightnessAdjust      0x1008ff3b  /* Invoke brightness adj. UI   */
#define XF86XK_Finance               0x1008ff3c  /* Display financial site      */
#define XF86XK_Community             0x1008ff3d  /* Display user's community    */
#define XF86XK_AudioRewind           0x1008ff3e  /* "rewind" audio track        */
#define XF86XK_BackForward           0x1008ff3f  /* ??? */
#define XF86XK_Launch0               0x1008ff40  /* Launch Application          */
#define XF86XK_Launch1               0x1008ff41  /* Launch Application          */
#define XF86XK_Launch2               0x1008ff42  /* Launch Application          */
#define XF86XK_Launch3               0x1008ff43  /* Launch Application          */
#define XF86XK_Launch4               0x1008ff44  /* Launch Application          */
#define XF86XK_Launch5               0x1008ff45  /* Launch Application          */
#define XF86XK_Launch6               0x1008ff46  /* Launch Application          */
#define XF86XK_Launch7               0x1008ff47  /* Launch Application          */
#define XF86XK_Launch8               0x1008ff48  /* Launch Application          */
#define XF86XK_Launch9               0x1008ff49  /* Launch Application          */
#define XF86XK_LaunchA               0x1008ff4a  /* Launch Application          */
#define XF86XK_LaunchB               0x1008ff4b  /* Launch Application          */
#define XF86XK_LaunchC               0x1008ff4c  /* Launch Application          */
#define XF86XK_LaunchD               0x1008ff4d  /* Launch Application          */
#define XF86XK_LaunchE               0x1008ff4e  /* Launch Application          */
#define XF86XK_LaunchF               0x1008ff4f  /* Launch Application          */

#define XF86XK_ApplicationLeft       0x1008ff50  /* switch to application, left */
#define XF86XK_ApplicationRight      0x1008ff51  /* switch to application, right*/
#define XF86XK_Book                  0x1008ff52  /* Launch bookreader           */
#define XF86XK_CD                    0x1008ff53  /* Launch CD/DVD player        */
#define XF86XK_Calculater            0x1008ff54  /* Launch Calculater           */
#define XF86XK_Clear                 0x1008ff55  /* Clear window, screen        */
#define XF86XK_Close                 0x1008ff56  /* Close window                */
#define XF86XK_Copy                  0x1008ff57  /* Copy selection              */
#define XF86XK_Cut                   0x1008ff58  /* Cut selection               */
#define XF86XK_Display               0x1008ff59  /* Output switch key           */
#define XF86XK_DOS                   0x1008ff5a  /* Launch DOS (emulation)      */
#define XF86XK_Documents             0x1008ff5b  /* Open documents window       */
#define XF86XK_Excel                 0x1008ff5c  /* Launch spread sheet         */
#define XF86XK_Explorer              0x1008ff5d  /* Launch file explorer        */
#define XF86XK_Game                  0x1008ff5e  /* Launch game                 */
#define XF86XK_Go                    0x1008ff5f  /* Go to URL                   */
#define XF86XK_iTouch                0x1008ff60  /* Logitech iTouch- don't use  */
#define XF86XK_LogOff                0x1008ff61  /* Log off system              */
#define XF86XK_Market                0x1008ff62  /* ??                          */
#define XF86XK_Meeting               0x1008ff63  /* enter meeting in calendar   */
#define XF86XK_MenuKB                0x1008ff65  /* distinguish keyboard from PB */
#define XF86XK_MenuPB                0x1008ff66  /* distinguish PB from keyboard */
#define XF86XK_MySites               0x1008ff67  /* Favourites                  */
#define XF86XK_New                   0x1008ff68  /* New (folder, document...    */
#define XF86XK_News                  0x1008ff69  /* News                        */
#define XF86XK_OfficeHome            0x1008ff6a  /* Office home (old Staroffice)*/
#define XF86XK_Open                  0x1008ff6b  /* Open                        */
#define XF86XK_Option                0x1008ff6c  /* ?? */
#define XF86XK_Paste                 0x1008ff6d  /* Paste                       */
#define XF86XK_Phone                 0x1008ff6e  /* Launch phone; dial number   */
#define XF86XK_Q                     0x1008ff70  /* Compaq's Q - don't use      */
#define XF86XK_Reply                 0x1008ff72  /* Reply e.g., mail            */
#define XF86XK_Reload                0x1008ff73  /* Reload web page, file, etc. */
#define XF86XK_RotateWindows         0x1008ff74  /* Rotate windows e.g. xrandr  */
#define XF86XK_RotationPB            0x1008ff75  /* don't use                   */
#define XF86XK_RotationKB            0x1008ff76  /* don't use                   */
#define XF86XK_Save                  0x1008ff77  /* Save (file, document, state */
#define XF86XK_ScrollUp              0x1008ff78  /* Scroll window/contents up   */
#define XF86XK_ScrollDown            0x1008ff79  /* Scrool window/contentd down */
#define XF86XK_ScrollClick           0x1008ff7a  /* Use XKB mousekeys instead   */
#define XF86XK_Send                  0x1008ff7b  /* Send mail, file, object     */
#define XF86XK_Spell                 0x1008ff7c  /* Spell checker               */
#define XF86XK_SplitScreen           0x1008ff7d  /* Split window or screen      */
#define XF86XK_Support               0x1008ff7e  /* Get support (??)            */
#define XF86XK_TaskPane              0x1008ff7f  /* Show tasks */
#define XF86XK_Terminal              0x1008ff80  /* Launch terminal emulator    */
#define XF86XK_Tools                 0x1008ff81  /* toolbox of desktop/app.     */
#define XF86XK_Travel                0x1008ff82  /* ?? */
#define XF86XK_UserPB                0x1008ff84  /* ?? */
#define XF86XK_User1KB               0x1008ff85  /* ?? */
#define XF86XK_User2KB               0x1008ff86  /* ?? */
#define XF86XK_Video                 0x1008ff87  /* Launch video player       */
#define XF86XK_WheelButton           0x1008ff88  /* button from a mouse wheel */
#define XF86XK_Word                  0x1008ff89  /* Launch word processor     */
#define XF86XK_Xfer                  0x1008ff8a
#define XF86XK_ZoomIn                0x1008ff8b  /* zoom in view, map, etc.   */
#define XF86XK_ZoomOut               0x1008ff8c  /* zoom out view, map, etc.  */

#define XF86XK_Away                  0x1008ff8d  /* mark yourself as away     */
#define XF86XK_Messenger             0x1008ff8e  /* as in instant messaging   */
#define XF86XK_WebCam                0x1008ff8f  /* Launch web camera app.    */
#define XF86XK_MailForward           0x1008ff90  /* Forward in mail           */
#define XF86XK_Pictures              0x1008ff91  /* Show pictures             */
#define XF86XK_Music                 0x1008ff92  /* Launch music application  */

#define XF86XK_Battery               0x1008ff93  /* Display battery information */
#define XF86XK_Bluetooth             0x1008ff94  /* Enable/disable Bluetooth    */
#define XF86XK_WLAN                  0x1008ff95  /* Enable/disable WLAN         */
#define XF86XK_UWB                   0x1008ff96  /* Enable/disable UWB	    */

#define XF86XK_AudioForward          0x1008ff97  /* fast-forward audio track    */
#define XF86XK_AudioRepeat           0x1008ff98  /* toggle repeat mode          */
#define XF86XK_AudioRandomPlay       0x1008ff99  /* toggle shuffle mode         */
#define XF86XK_Subtitle              0x1008ff9a  /* cycle through subtitle      */
#define XF86XK_AudioCycleTrack       0x1008ff9b  /* cycle through audio tracks  */
#define XF86XK_CycleAngle            0x1008ff9c  /* cycle through angles        */
#define XF86XK_FrameBack             0x1008ff9d  /* video: go one frame back    */
#define XF86XK_FrameForward          0x1008ff9e  /* video: go one frame forward */
#define XF86XK_Time                  0x1008ff9f  /* display, or shows an entry for time seeking */
#define XF86XK_Select                0x1008ffa0  /* Select button on joypads and remotes */
#define XF86XK_View                  0x1008ffa1  /* Show a view options/properties */
#define XF86XK_TopMenu               0x1008ffa2  /* Go to a top-level menu in a video */

#define XF86XK_Red                   0x1008ffa3  /* Red button                  */
#define XF86XK_Green                 0x1008ffa4  /* Green button                */
#define XF86XK_Yellow                0x1008ffa5  /* Yellow button               */
#define XF86XK_Blue                  0x1008ffa6  /* Blue button                 */

#define XF86XK_Suspend               0x1008ffa7  /* Sleep to RAM                */
#define XF86XK_Hibernate             0x1008ffa8  /* Sleep to disk               */
#define XF86XK_TouchpadToggle        0x1008ffa9  /* Toggle between touchpad/trackstick */
#define XF86XK_TouchpadOn            0x1008ffb0  /* The touchpad got switched on */
#define XF86XK_TouchpadOff           0x1008ffb1  /* The touchpad got switched off */

#define XF86XK_AudioMicMute          0x1008ffb2  /* Mute the Mic from the system */

#define XF86XK_Keyboard              0x1008ffb3  /* User defined keyboard related action */

#define XF86XK_WWAN                  0x1008ffb4  /* Toggle WWAN (LTE, UMTS, etc.) radio */
#define XF86XK_RFKill                0x1008ffb5  /* Toggle radios on/off */

#define XF86XK_AudioPreset           0x1008ffb6  /* Select equalizer preset, e.g. theatre-mode */

#define XF86XK_RotationLockToggle    0x1008ffb7  /* Toggle screen rotation lock on/off */

#define XF86XK_FullScreen            0x1008ffb8  /* Toggle fullscreen */

/* Keys for special action keys (hot keys) */
/* Virtual terminals on some operating systems */
#define XF86XK_Switch_VT_1           0x1008fe01
#define XF86XK_Switch_VT_2           0x1008fe02
#define XF86XK_Switch_VT_3           0x1008fe03
#define XF86XK_Switch_VT_4           0x1008fe04
#define XF86XK_Switch_VT_5           0x1008fe05
#define XF86XK_Switch_VT_6           0x1008fe06
#define XF86XK_Switch_VT_7           0x1008fe07
#define XF86XK_Switch_VT_8           0x1008fe08
#define XF86XK_Switch_VT_9           0x1008fe09
#define XF86XK_Switch_VT_10          0x1008fe0a
#define XF86XK_Switch_VT_11          0x1008fe0b
#define XF86XK_Switch_VT_12          0x1008fe0c

#define XF86XK_Ungrab                0x1008fe20  /* force ungrab               */
#define XF86XK_ClearGrab             0x1008fe21  /* kill application with grab */
#define XF86XK_Next_VMode            0x1008fe22  /* next video mode available  */
#define XF86XK_Prev_VMode            0x1008fe23  /* prev. video mode available */
#define XF86XK_LogWindowTree         0x1008fe24  /* print window tree to log   */
#define XF86XK_LogGrabInfo           0x1008fe25  /* print all active grabs to log */


/*
 * Reserved range for evdev symbols: 0x10081000-0x10081FFF
 *
 * Key syms within this range must match the Linux kernel
 * input-event-codes.h file in the format:
 *     XF86XK_CamelCaseKernelName	_EVDEVK(kernel value)
 * For example, the kernel
 *   #define KEY_MACRO_RECORD_START	0x2b0
 * effectively ends up as:
 *   #define XF86XK_MacroRecordStart	0x100812b0
 *
 * For historical reasons, some keysyms within the reserved range will be
 * missing, most notably all "normal" keys that are mapped through default
 * XKB layouts (e.g. KEY_Q).
 *
 * CamelCasing is done with a human control as last authority, e.g. see VOD
 * instead of Vod for the Video on Demand key.
 *
 * The format for #defines is strict:
 *
 * #define XF86XK_FOO<tab...>_EVDEVK(0xABC)<tab><tab> |* kver KEY_FOO *|
 *
 * Where
 * - alignment by tabs
 * - the _EVDEVK macro must be used
 * - the hex code must be in uppercase hex
 * - the kernel version (kver) is in the form v5.10
 * - kver and key name are within a slash-star comment (a pipe is used in
 *   this example for technical reasons)
 * These #defines are parsed by scripts. Do not stray from the given format.
 *
 * Where the evdev keycode is mapped to a different symbol, please add a
 * comment line starting with Use: but otherwise the same format, e.g.
 *  Use: XF86XK_RotationLockToggle	_EVDEVK(0x231)		   v4.16 KEY_ROTATE_LOCK_TOGGLE
 *
 */
#define _EVDEVK(_v) (0x10081000 + _v)
/* Use: XF86XK_Eject                    _EVDEVK(0x0a2)             KEY_EJECTCLOSECD */
/* Use: XF86XK_New                      _EVDEVK(0x0b5)     v2.6.14 KEY_NEW */
/* Use: XK_Redo                         _EVDEVK(0x0b6)     v2.6.14 KEY_REDO */
/* KEY_DASHBOARD has been mapped to LaunchB in xkeyboard-config since 2011 */
/* Use: XF86XK_LaunchB                  _EVDEVK(0x0cc)     v2.6.28 KEY_DASHBOARD */
/* Use: XF86XK_Display                  _EVDEVK(0x0e3)     v2.6.12 KEY_SWITCHVIDEOMODE */
/* Use: XF86XK_KbdLightOnOff            _EVDEVK(0x0e4)     v2.6.12 KEY_KBDILLUMTOGGLE */
/* Use: XF86XK_KbdBrightnessDown        _EVDEVK(0x0e5)     v2.6.12 KEY_KBDILLUMDOWN */
/* Use: XF86XK_KbdBrightnessUp          _EVDEVK(0x0e6)     v2.6.12 KEY_KBDILLUMUP */
/* Use: XF86XK_Send                     _EVDEVK(0x0e7)     v2.6.14 KEY_SEND */
/* Use: XF86XK_Reply                    _EVDEVK(0x0e8)     v2.6.14 KEY_REPLY */
/* Use: XF86XK_MailForward              _EVDEVK(0x0e9)     v2.6.14 KEY_FORWARDMAIL */
/* Use: XF86XK_Save                     _EVDEVK(0x0ea)     v2.6.14 KEY_SAVE */
/* Use: XF86XK_Documents                _EVDEVK(0x0eb)     v2.6.14 KEY_DOCUMENTS */
/* Use: XF86XK_Battery                  _EVDEVK(0x0ec)     v2.6.17 KEY_BATTERY */
/* Use: XF86XK_Bluetooth                _EVDEVK(0x0ed)     v2.6.19 KEY_BLUETOOTH */
/* Use: XF86XK_WLAN                     _EVDEVK(0x0ee)     v2.6.19 KEY_WLAN */
/* Use: XF86XK_UWB                      _EVDEVK(0x0ef)     v2.6.24 KEY_UWB */
/* Use: XF86XK_Next_VMode               _EVDEVK(0x0f1)     v2.6.23 KEY_VIDEO_NEXT */
/* Use: XF86XK_Prev_VMode               _EVDEVK(0x0f2)     v2.6.23 KEY_VIDEO_PREV */
/* Use: XF86XK_MonBrightnessCycle       _EVDEVK(0x0f3)     v2.6.23 KEY_BRIGHTNESS_CYCLE */
#define XF86XK_BrightnessAuto           _EVDEVK(0x0f4)  /* v3.16   KEY_BRIGHTNESS_AUTO */
#define XF86XK_DisplayOff               _EVDEVK(0x0f5)  /* v2.6.23 KEY_DISPLAY_OFF */
/* Use: XF86XK_WWAN                     _EVDEVK(0x0f6)     v3.13   KEY_WWAN */
/* Use: XF86XK_RFKill                   _EVDEVK(0x0f7)     v2.6.33 KEY_RFKILL */
/* Use: XF86XK_AudioMicMute             _EVDEVK(0x0f8)     v3.1    KEY_MICMUTE */
#define XF86XK_Info                     _EVDEVK(0x166)  /*         KEY_INFO */
/* Use: XF86XK_CycleAngle               _EVDEVK(0x173)             KEY_ANGLE */
/* Use: XF86XK_FullScreen               _EVDEVK(0x174)     v5.1    KEY_FULL_SCREEN */
#define XF86XK_AspectRatio              _EVDEVK(0x177)  /* v5.1    KEY_ASPECT_RATIO */
#define XF86XK_DVD                      _EVDEVK(0x185)  /*         KEY_DVD */
#define XF86XK_Audio                    _EVDEVK(0x188)  /*         KEY_AUDIO */
/* Use: XF86XK_Video                    _EVDEVK(0x189)             KEY_VIDEO */
/* Use: XF86XK_Calendar                 _EVDEVK(0x18d)             KEY_CALENDAR */
#define XF86XK_ChannelUp                _EVDEVK(0x192)  /*         KEY_CHANNELUP */
#define XF86XK_ChannelDown              _EVDEVK(0x193)  /*         KEY_CHANNELDOWN */
/* Use: XF86XK_AudioRandomPlay          _EVDEVK(0x19a)             KEY_SHUFFLE */
#define XF86XK_Break                    _EVDEVK(0x19b)  /*         KEY_BREAK */
#define XF86XK_VideoPhone               _EVDEVK(0x1a0)  /* v2.6.20 KEY_VIDEOPHONE */
/* Use: XF86XK_Game                     _EVDEVK(0x1a1)     v2.6.20 KEY_GAMES */
/* Use: XF86XK_ZoomIn                   _EVDEVK(0x1a2)     v2.6.20 KEY_ZOOMIN */
/* Use: XF86XK_ZoomOut                  _EVDEVK(0x1a3)     v2.6.20 KEY_ZOOMOUT */
#define XF86XK_ZoomReset                _EVDEVK(0x1a4)  /* v2.6.20 KEY_ZOOMRESET */
/* Use: XF86XK_Word                     _EVDEVK(0x1a5)     v2.6.20 KEY_WORDPROCESSOR */
#define XF86XK_Editor                   _EVDEVK(0x1a6)  /* v2.6.20 KEY_EDITOR */
/* Use: XF86XK_Excel                    _EVDEVK(0x1a7)     v2.6.20 KEY_SPREADSHEET */
#define XF86XK_GraphicsEditor           _EVDEVK(0x1a8)  /* v2.6.20 KEY_GRAPHICSEDITOR */
#define XF86XK_Presentation             _EVDEVK(0x1a9)  /* v2.6.20 KEY_PRESENTATION */
#define XF86XK_Database                 _EVDEVK(0x1aa)  /* v2.6.20 KEY_DATABASE */
/* Use: XF86XK_News                     _EVDEVK(0x1ab)     v2.6.20 KEY_NEWS */
#define XF86XK_Voicemail                _EVDEVK(0x1ac)  /* v2.6.20 KEY_VOICEMAIL */
#define XF86XK_Addressbook              _EVDEVK(0x1ad)  /* v2.6.20 KEY_ADDRESSBOOK */
/* Use: XF86XK_Messenger                _EVDEVK(0x1ae)     v2.6.20 KEY_MESSENGER */
#define XF86XK_DisplayToggle            _EVDEVK(0x1af)  /* v2.6.20 KEY_DISPLAYTOGGLE */
#define XF86XK_SpellCheck               _EVDEVK(0x1b0)  /* v2.6.24 KEY_SPELLCHECK */
/* Use: XF86XK_LogOff                   _EVDEVK(0x1b1)     v2.6.24 KEY_LOGOFF */
/* Use: XK_dollar                       _EVDEVK(0x1b2)     v2.6.24 KEY_DOLLAR */
/* Use: XK_EuroSign                     _EVDEVK(0x1b3)     v2.6.24 KEY_EURO */
/* Use: XF86XK_FrameBack                _EVDEVK(0x1b4)     v2.6.24 KEY_FRAMEBACK */
/* Use: XF86XK_FrameForward             _EVDEVK(0x1b5)     v2.6.24 KEY_FRAMEFORWARD */
#define XF86XK_ContextMenu              _EVDEVK(0x1b6)  /* v2.6.24 KEY_CONTEXT_MENU */
#define XF86XK_MediaRepeat              _EVDEVK(0x1b7)  /* v2.6.26 KEY_MEDIA_REPEAT */
#define XF86XK_10ChannelsUp             _EVDEVK(0x1b8)  /* v2.6.38 KEY_10CHANNELSUP */
#define XF86XK_10ChannelsDown           _EVDEVK(0x1b9)  /* v2.6.38 KEY_10CHANNELSDOWN */
#define XF86XK_Images                   _EVDEVK(0x1ba)  /* v2.6.39 KEY_IMAGES */
#define XF86XK_NotificationCenter       _EVDEVK(0x1bc)  /* v5.10   KEY_NOTIFICATION_CENTER */
#define XF86XK_PickupPhone              _EVDEVK(0x1bd)  /* v5.10   KEY_PICKUP_PHONE */
#define XF86XK_HangupPhone              _EVDEVK(0x1be)  /* v5.10   KEY_HANGUP_PHONE */
#define XF86XK_Fn                       _EVDEVK(0x1d0)  /*         KEY_FN */
#define XF86XK_Fn_Esc                   _EVDEVK(0x1d1)  /*         KEY_FN_ESC */
#define XF86XK_FnRightShift             _EVDEVK(0x1e5)  /* v5.10   KEY_FN_RIGHT_SHIFT */
/* Use: XK_braille_dot_1                _EVDEVK(0x1f1)     v2.6.17 KEY_BRL_DOT1 */
/* Use: XK_braille_dot_2                _EVDEVK(0x1f2)     v2.6.17 KEY_BRL_DOT2 */
/* Use: XK_braille_dot_3                _EVDEVK(0x1f3)     v2.6.17 KEY_BRL_DOT3 */
/* Use: XK_braille_dot_4                _EVDEVK(0x1f4)     v2.6.17 KEY_BRL_DOT4 */
/* Use: XK_braille_dot_5                _EVDEVK(0x1f5)     v2.6.17 KEY_BRL_DOT5 */
/* Use: XK_braille_dot_6                _EVDEVK(0x1f6)     v2.6.17 KEY_BRL_DOT6 */
/* Use: XK_braille_dot_7                _EVDEVK(0x1f7)     v2.6.17 KEY_BRL_DOT7 */
/* Use: XK_braille_dot_8                _EVDEVK(0x1f8)     v2.6.17 KEY_BRL_DOT8 */
/* Use: XK_braille_dot_9                _EVDEVK(0x1f9)     v2.6.23 KEY_BRL_DOT9 */
/* Use: XK_braille_dot_1                _EVDEVK(0x1fa)     v2.6.23 KEY_BRL_DOT10 */
#define XF86XK_Numeric0                 _EVDEVK(0x200)  /* v2.6.28 KEY_NUMERIC_0 */
#define XF86XK_Numeric1                 _EVDEVK(0x201)  /* v2.6.28 KEY_NUMERIC_1 */
#define XF86XK_Numeric2                 _EVDEVK(0x202)  /* v2.6.28 KEY_NUMERIC_2 */
#define XF86XK_Numeric3                 _EVDEVK(0x203)  /* v2.6.28 KEY_NUMERIC_3 */
#define XF86XK_Numeric4                 _EVDEVK(0x204)  /* v2.6.28 KEY_NUMERIC_4 */
#define XF86XK_Numeric5                 _EVDEVK(0x205)  /* v2.6.28 KEY_NUMERIC_5 */
#define XF86XK_Numeric6                 _EVDEVK(0x206)  /* v2.6.28 KEY_NUMERIC_6 */
#define XF86XK_Numeric7                 _EVDEVK(0x207)  /* v2.6.28 KEY_NUMERIC_7 */
#define XF86XK_Numeric8                 _EVDEVK(0x208)  /* v2.6.28 KEY_NUMERIC_8 */
#define XF86XK_Numeric9                 _EVDEVK(0x209)  /* v2.6.28 KEY_NUMERIC_9 */
#define XF86XK_NumericStar              _EVDEVK(0x20a)  /* v2.6.28 KEY_NUMERIC_STAR */
#define XF86XK_NumericPound             _EVDEVK(0x20b)  /* v2.6.28 KEY_NUMERIC_POUND */
#define XF86XK_NumericA                 _EVDEVK(0x20c)  /* v4.1    KEY_NUMERIC_A */
#define XF86XK_NumericB                 _EVDEVK(0x20d)  /* v4.1    KEY_NUMERIC_B */
#define XF86XK_NumericC                 _EVDEVK(0x20e)  /* v4.1    KEY_NUMERIC_C */
#define XF86XK_NumericD                 _EVDEVK(0x20f)  /* v4.1    KEY_NUMERIC_D */
#define XF86XK_CameraFocus              _EVDEVK(0x210)  /* v2.6.33 KEY_CAMERA_FOCUS */
#define XF86XK_WPSButton                _EVDEVK(0x211)  /* v2.6.34 KEY_WPS_BUTTON */
/* Use: XF86XK_TouchpadToggle           _EVDEVK(0x212)     v2.6.37 KEY_TOUCHPAD_TOGGLE */
/* Use: XF86XK_TouchpadOn               _EVDEVK(0x213)     v2.6.37 KEY_TOUCHPAD_ON */
/* Use: XF86XK_TouchpadOff              _EVDEVK(0x214)     v2.6.37 KEY_TOUCHPAD_OFF */
#define XF86XK_CameraZoomIn             _EVDEVK(0x215)  /* v2.6.39 KEY_CAMERA_ZOOMIN */
#define XF86XK_CameraZoomOut            _EVDEVK(0x216)  /* v2.6.39 KEY_CAMERA_ZOOMOUT */
#define XF86XK_CameraUp                 _EVDEVK(0x217)  /* v2.6.39 KEY_CAMERA_UP */
#define XF86XK_CameraDown               _EVDEVK(0x218)  /* v2.6.39 KEY_CAMERA_DOWN */
#define XF86XK_CameraLeft               _EVDEVK(0x219)  /* v2.6.39 KEY_CAMERA_LEFT */
#define XF86XK_CameraRight              _EVDEVK(0x21a)  /* v2.6.39 KEY_CAMERA_RIGHT */
#define XF86XK_AttendantOn              _EVDEVK(0x21b)  /* v3.10   KEY_ATTENDANT_ON */
#define XF86XK_AttendantOff             _EVDEVK(0x21c)  /* v3.10   KEY_ATTENDANT_OFF */
#define XF86XK_AttendantToggle          _EVDEVK(0x21d)  /* v3.10   KEY_ATTENDANT_TOGGLE */
#define XF86XK_LightsToggle             _EVDEVK(0x21e)  /* v3.10   KEY_LIGHTS_TOGGLE */
#define XF86XK_ALSToggle                _EVDEVK(0x230)  /* v3.13   KEY_ALS_TOGGLE */
/* Use: XF86XK_RotationLockToggle       _EVDEVK(0x231)     v4.16   KEY_ROTATE_LOCK_TOGGLE */
#define XF86XK_Buttonconfig             _EVDEVK(0x240)  /* v3.16   KEY_BUTTONCONFIG */
#define XF86XK_Taskmanager              _EVDEVK(0x241)  /* v3.16   KEY_TASKMANAGER */
#define XF86XK_Journal                  _EVDEVK(0x242)  /* v3.16   KEY_JOURNAL */
#define XF86XK_ControlPanel             _EVDEVK(0x243)  /* v3.16   KEY_CONTROLPANEL */
#define XF86XK_AppSelect                _EVDEVK(0x244)  /* v3.16   KEY_APPSELECT */
#define XF86XK_Screensaver              _EVDEVK(0x245)  /* v3.16   KEY_SCREENSAVER */
#define XF86XK_VoiceCommand             _EVDEVK(0x246)  /* v3.16   KEY_VOICECOMMAND */
#define XF86XK_Assistant                _EVDEVK(0x247)  /* v4.13   KEY_ASSISTANT */
/* Use: XK_ISO_Next_Group               _EVDEVK(0x248)     v5.2    KEY_KBD_LAYOUT_NEXT */
#define XF86XK_EmojiPicker              _EVDEVK(0x249)  /* v5.13   KEY_EMOJI_PICKER */
#define XF86XK_Dictate                  _EVDEVK(0x24a)  /* v5.17   KEY_DICTATE */
#define XF86XK_CameraAccessEnable       _EVDEVK(0x24b)  /* v6.2    KEY_CAMERA_ACCESS_ENABLE */
#define XF86XK_CameraAccessDisable      _EVDEVK(0x24c)  /* v6.2    KEY_CAMERA_ACCESS_DISABLE */
#define XF86XK_CameraAccessToggle       _EVDEVK(0x24d)  /* v6.2    KEY_CAMERA_ACCESS_TOGGLE */
#define XF86XK_BrightnessMin            _EVDEVK(0x250)  /* v3.16   KEY_BRIGHTNESS_MIN */
#define XF86XK_BrightnessMax            _EVDEVK(0x251)  /* v3.16   KEY_BRIGHTNESS_MAX */
#define XF86XK_KbdInputAssistPrev       _EVDEVK(0x260)  /* v3.18   KEY_KBDINPUTASSIST_PREV */
#define XF86XK_KbdInputAssistNext       _EVDEVK(0x261)  /* v3.18   KEY_KBDINPUTASSIST_NEXT */
#define XF86XK_KbdInputAssistPrevgroup  _EVDEVK(0x262)  /* v3.18   KEY_KBDINPUTASSIST_PREVGROUP */
#define XF86XK_KbdInputAssistNextgroup  _EVDEVK(0x263)  /* v3.18   KEY_KBDINPUTASSIST_NEXTGROUP */
#define XF86XK_KbdInputAssistAccept     _EVDEVK(0x264)  /* v3.18   KEY_KBDINPUTASSIST_ACCEPT */
#define XF86XK_KbdInputAssistCancel     _EVDEVK(0x265)  /* v3.18   KEY_KBDINPUTASSIST_CANCEL */
#define XF86XK_RightUp                  _EVDEVK(0x266)  /* v4.7    KEY_RIGHT_UP */
#define XF86XK_RightDown                _EVDEVK(0x267)  /* v4.7    KEY_RIGHT_DOWN */
#define XF86XK_LeftUp                   _EVDEVK(0x268)  /* v4.7    KEY_LEFT_UP */
#define XF86XK_LeftDown                 _EVDEVK(0x269)  /* v4.7    KEY_LEFT_DOWN */
#define XF86XK_RootMenu                 _EVDEVK(0x26a)  /* v4.7    KEY_ROOT_MENU */
#define XF86XK_MediaTopMenu             _EVDEVK(0x26b)  /* v4.7    KEY_MEDIA_TOP_MENU */
#define XF86XK_Numeric11                _EVDEVK(0x26c)  /* v4.7    KEY_NUMERIC_11 */
#define XF86XK_Numeric12                _EVDEVK(0x26d)  /* v4.7    KEY_NUMERIC_12 */
#define XF86XK_AudioDesc                _EVDEVK(0x26e)  /* v4.7    KEY_AUDIO_DESC */
#define XF86XK_3DMode                   _EVDEVK(0x26f)  /* v4.7    KEY_3D_MODE */
#define XF86XK_NextFavorite             _EVDEVK(0x270)  /* v4.7    KEY_NEXT_FAVORITE */
#define XF86XK_StopRecord               _EVDEVK(0x271)  /* v4.7    KEY_STOP_RECORD */
#define XF86XK_PauseRecord              _EVDEVK(0x272)  /* v4.7    KEY_PAUSE_RECORD */
#define XF86XK_VOD                      _EVDEVK(0x273)  /* v4.7    KEY_VOD */
#define XF86XK_Unmute                   _EVDEVK(0x274)  /* v4.7    KEY_UNMUTE */
#define XF86XK_FastReverse              _EVDEVK(0x275)  /* v4.7    KEY_FASTREVERSE */
#define XF86XK_SlowReverse              _EVDEVK(0x276)  /* v4.7    KEY_SLOWREVERSE */
#define XF86XK_Data                     _EVDEVK(0x277)  /* v4.7    KEY_DATA */
#define XF86XK_OnScreenKeyboard         _EVDEVK(0x278)  /* v4.12   KEY_ONSCREEN_KEYBOARD */
#define XF86XK_PrivacyScreenToggle      _EVDEVK(0x279)  /* v5.5    KEY_PRIVACY_SCREEN_TOGGLE */
#define XF86XK_SelectiveScreenshot      _EVDEVK(0x27a)  /* v5.6    KEY_SELECTIVE_SCREENSHOT */
#define XF86XK_NextElement              _EVDEVK(0x27b)  /* v5.18   KEY_NEXT_ELEMENT */
#define XF86XK_PreviousElement          _EVDEVK(0x27c)  /* v5.18   KEY_PREVIOUS_ELEMENT */
#define XF86XK_AutopilotEngageToggle    _EVDEVK(0x27d)  /* v5.18   KEY_AUTOPILOT_ENGAGE_TOGGLE */
#define XF86XK_MarkWaypoint             _EVDEVK(0x27e)  /* v5.18   KEY_MARK_WAYPOINT */
#define XF86XK_Sos                      _EVDEVK(0x27f)  /* v5.18   KEY_SOS */
#define XF86XK_NavChart                 _EVDEVK(0x280)  /* v5.18   KEY_NAV_CHART */
#define XF86XK_FishingChart             _EVDEVK(0x281)  /* v5.18   KEY_FISHING_CHART */
#define XF86XK_SingleRangeRadar         _EVDEVK(0x282)  /* v5.18   KEY_SINGLE_RANGE_RADAR */
#define XF86XK_DualRangeRadar           _EVDEVK(0x283)  /* v5.18   KEY_DUAL_RANGE_RADAR */
#define XF86XK_RadarOverlay             _EVDEVK(0x284)  /* v5.18   KEY_RADAR_OVERLAY */
#define XF86XK_TraditionalSonar         _EVDEVK(0x285)  /* v5.18   KEY_TRADITIONAL_SONAR */
#define XF86XK_ClearvuSonar             _EVDEVK(0x286)  /* v5.18   KEY_CLEARVU_SONAR */
#define XF86XK_SidevuSonar              _EVDEVK(0x287)  /* v5.18   KEY_SIDEVU_SONAR */
#define XF86XK_NavInfo                  _EVDEVK(0x288)  /* v5.18   KEY_NAV_INFO */
/* Use: XF86XK_BrightnessAdjust         _EVDEVK(0x289)     v5.18   KEY_BRIGHTNESS_MENU */
#define XF86XK_Macro1                   _EVDEVK(0x290)  /* v5.5    KEY_MACRO1 */
#define XF86XK_Macro2                   _EVDEVK(0x291)  /* v5.5    KEY_MACRO2 */
#define XF86XK_Macro3                   _EVDEVK(0x292)  /* v5.5    KEY_MACRO3 */
#define XF86XK_Macro4                   _EVDEVK(0x293)  /* v5.5    KEY_MACRO4 */
#define XF86XK_Macro5                   _EVDEVK(0x294)  /* v5.5    KEY_MACRO5 */
#define XF86XK_Macro6                   _EVDEVK(0x295)  /* v5.5    KEY_MACRO6 */
#define XF86XK_Macro7                   _EVDEVK(0x296)  /* v5.5    KEY_MACRO7 */
#define XF86XK_Macro8                   _EVDEVK(0x297)  /* v5.5    KEY_MACRO8 */
#define XF86XK_Macro9                   _EVDEVK(0x298)  /* v5.5    KEY_MACRO9 */
#define XF86XK_Macro10                  _EVDEVK(0x299)  /* v5.5    KEY_MACRO10 */
#define XF86XK_Macro11                  _EVDEVK(0x29a)  /* v5.5    KEY_MACRO11 */
#define XF86XK_Macro12                  _EVDEVK(0x29b)  /* v5.5    KEY_MACRO12 */
#define XF86XK_Macro13                  _EVDEVK(0x29c)  /* v5.5    KEY_MACRO13 */
#define XF86XK_Macro14                  _EVDEVK(0x29d)  /* v5.5    KEY_MACRO14 */
#define XF86XK_Macro15                  _EVDEVK(0x29e)  /* v5.5    KEY_MACRO15 */
#define XF86XK_Macro16                  _EVDEVK(0x29f)  /* v5.5    KEY_MACRO16 */
#define XF86XK_Macro17                  _EVDEVK(0x2a0)  /* v5.5    KEY_MACRO17 */
#define XF86XK_Macro18                  _EVDEVK(0x2a1)  /* v5.5    KEY_MACRO18 */
#define XF86XK_Macro19                  _EVDEVK(0x2a2)  /* v5.5    KEY_MACRO19 */
#define XF86XK_Macro20                  _EVDEVK(0x2a3)  /* v5.5    KEY_MACRO20 */
#define XF86XK_Macro21                  _EVDEVK(0x2a4)  /* v5.5    KEY_MACRO21 */
#define XF86XK_Macro22                  _EVDEVK(0x2a5)  /* v5.5    KEY_MACRO22 */
#define XF86XK_Macro23                  _EVDEVK(0x2a6)  /* v5.5    KEY_MACRO23 */
#define XF86XK_Macro24                  _EVDEVK(0x2a7)  /* v5.5    KEY_MACRO24 */
#define XF86XK_Macro25                  _EVDEVK(0x2a8)  /* v5.5    KEY_MACRO25 */
#define XF86XK_Macro26                  _EVDEVK(0x2a9)  /* v5.5    KEY_MACRO26 */
#define XF86XK_Macro27                  _EVDEVK(0x2aa)  /* v5.5    KEY_MACRO27 */
#define XF86XK_Macro28                  _EVDEVK(0x2ab)  /* v5.5    KEY_MACRO28 */
#define XF86XK_Macro29                  _EVDEVK(0x2ac)  /* v5.5    KEY_MACRO29 */
#define XF86XK_Macro30                  _EVDEVK(0x2ad)  /* v5.5    KEY_MACRO30 */
#define XF86XK_MacroRecordStart         _EVDEVK(0x2b0)  /* v5.5    KEY_MACRO_RECORD_START */
#define XF86XK_MacroRecordStop          _EVDEVK(0x2b1)  /* v5.5    KEY_MACRO_RECORD_STOP */
#define XF86XK_MacroPresetCycle         _EVDEVK(0x2b2)  /* v5.5    KEY_MACRO_PRESET_CYCLE */
#define XF86XK_MacroPreset1             _EVDEVK(0x2b3)  /* v5.5    KEY_MACRO_PRESET1 */
#define XF86XK_MacroPreset2             _EVDEVK(0x2b4)  /* v5.5    KEY_MACRO_PRESET2 */
#define XF86XK_MacroPreset3             _EVDEVK(0x2b5)  /* v5.5    KEY_MACRO_PRESET3 */
#define XF86XK_KbdLcdMenu1              _EVDEVK(0x2b8)  /* v5.5    KEY_KBD_LCD_MENU1 */
#define XF86XK_KbdLcdMenu2              _EVDEVK(0x2b9)  /* v5.5    KEY_KBD_LCD_MENU2 */
#define XF86XK_KbdLcdMenu3              _EVDEVK(0x2ba)  /* v5.5    KEY_KBD_LCD_MENU3 */
#define XF86XK_KbdLcdMenu4              _EVDEVK(0x2bb)  /* v5.5    KEY_KBD_LCD_MENU4 */
#define XF86XK_KbdLcdMenu5              _EVDEVK(0x2bc)  /* v5.5    KEY_KBD_LCD_MENU5 */
#undef _EVDEVK
