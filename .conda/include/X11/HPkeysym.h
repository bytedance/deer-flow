/*

Copyright 1987, 1998  The Open Group

Permission to use, copy, modify, distribute, and sell this software and its
documentation for any purpose is hereby granted without fee, provided that
the above copyright notice appear in all copies and that both that
copyright notice and this permission notice appear in supporting
documentation.

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE OPEN GROUP BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

Except as contained in this notice, the name of The Open Group shall
not be used in advertising or otherwise to promote the sale, use or
other dealings in this Software without prior written authorization
from The Open Group.

Copyright 1987 by Digital Equipment Corporation, Maynard, Massachusetts,

                        All Rights Reserved

Permission to use, copy, modify, and distribute this software and its
documentation for any purpose and without fee is hereby granted,
provided that the above copyright notice appear in all copies and that
both that copyright notice and this permission notice appear in
supporting documentation, and that the names of Hewlett Packard
or Digital not be
used in advertising or publicity pertaining to distribution of the
software without specific, written prior permission.

DIGITAL DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING
ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS, IN NO EVENT SHALL
DIGITAL BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR
ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS
SOFTWARE.

HEWLETT-PACKARD MAKES NO WARRANTY OF ANY KIND WITH REGARD
TO THIS SOFTWARE, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE.  Hewlett-Packard shall not be liable for errors
contained herein or direct, indirect, special, incidental or
consequential damages in connection with the furnishing,
performance, or use of this material.

*/

#ifndef _HPKEYSYM_H

#define _HPKEYSYM_H

#define hpXK_ClearLine               0x1000ff6f
#define hpXK_InsertLine              0x1000ff70
#define hpXK_DeleteLine              0x1000ff71
#define hpXK_InsertChar              0x1000ff72
#define hpXK_DeleteChar              0x1000ff73
#define hpXK_BackTab                 0x1000ff74
#define hpXK_KP_BackTab              0x1000ff75
#define hpXK_Modelock1               0x1000ff48
#define hpXK_Modelock2               0x1000ff49
#define hpXK_Reset                   0x1000ff6c
#define hpXK_System                  0x1000ff6d
#define hpXK_User                    0x1000ff6e
#define hpXK_mute_acute              0x100000a8
#define hpXK_mute_grave              0x100000a9
#define hpXK_mute_asciicircum        0x100000aa
#define hpXK_mute_diaeresis          0x100000ab
#define hpXK_mute_asciitilde         0x100000ac
#define hpXK_lira                    0x100000af
#define hpXK_guilder                 0x100000be
#define hpXK_Ydiaeresis              0x100000ee
#define hpXK_IO                      0x100000ee  /* deprecated alias for hpYdiaeresis */
#define hpXK_longminus               0x100000f6
#define hpXK_block                   0x100000fc


#ifndef _OSF_Keysyms
#define _OSF_Keysyms

#define osfXK_Copy                   0x1004ff02
#define osfXK_Cut                    0x1004ff03
#define osfXK_Paste                  0x1004ff04
#define osfXK_BackTab                0x1004ff07
#define osfXK_BackSpace              0x1004ff08
#define osfXK_Clear                  0x1004ff0b
#define osfXK_Escape                 0x1004ff1b
#define osfXK_AddMode                0x1004ff31
#define osfXK_PrimaryPaste           0x1004ff32
#define osfXK_QuickPaste             0x1004ff33
#define osfXK_PageLeft               0x1004ff40
#define osfXK_PageUp                 0x1004ff41
#define osfXK_PageDown               0x1004ff42
#define osfXK_PageRight              0x1004ff43
#define osfXK_Activate               0x1004ff44
#define osfXK_MenuBar                0x1004ff45
#define osfXK_Left                   0x1004ff51
#define osfXK_Up                     0x1004ff52
#define osfXK_Right                  0x1004ff53
#define osfXK_Down                   0x1004ff54
#define osfXK_EndLine                0x1004ff57
#define osfXK_BeginLine              0x1004ff58
#define osfXK_EndData                0x1004ff59
#define osfXK_BeginData              0x1004ff5a
#define osfXK_PrevMenu               0x1004ff5b
#define osfXK_NextMenu               0x1004ff5c
#define osfXK_PrevField              0x1004ff5d
#define osfXK_NextField              0x1004ff5e
#define osfXK_Select                 0x1004ff60
#define osfXK_Insert                 0x1004ff63
#define osfXK_Undo                   0x1004ff65
#define osfXK_Menu                   0x1004ff67
#define osfXK_Cancel                 0x1004ff69
#define osfXK_Help                   0x1004ff6a
#define osfXK_SelectAll              0x1004ff71
#define osfXK_DeselectAll            0x1004ff72
#define osfXK_Reselect               0x1004ff73
#define osfXK_Extend                 0x1004ff74
#define osfXK_Restore                0x1004ff78
#define osfXK_Delete                 0x1004ffff

#endif /* _OSF_Keysyms */


/**************************************************************
 * The use of the following macros is deprecated.
 * They are listed below only for backwards compatibility.
 */
#define XK_Reset                     0x1000ff6c  /* deprecated alias for hpReset */
#define XK_System                    0x1000ff6d  /* deprecated alias for hpSystem */
#define XK_User                      0x1000ff6e  /* deprecated alias for hpUser */
#define XK_ClearLine                 0x1000ff6f  /* deprecated alias for hpClearLine */
#define XK_InsertLine                0x1000ff70  /* deprecated alias for hpInsertLine */
#define XK_DeleteLine                0x1000ff71  /* deprecated alias for hpDeleteLine */
#define XK_InsertChar                0x1000ff72  /* deprecated alias for hpInsertChar */
#define XK_DeleteChar                0x1000ff73  /* deprecated alias for hpDeleteChar */
#define XK_BackTab                   0x1000ff74  /* deprecated alias for hpBackTab */
#define XK_KP_BackTab                0x1000ff75  /* deprecated alias for hpKP_BackTab */
#define XK_Ext16bit_L                0x1000ff76  /* deprecated */
#define XK_Ext16bit_R                0x1000ff77  /* deprecated */
#define XK_mute_acute                0x100000a8  /* deprecated alias for hpmute_acute */
#define XK_mute_grave                0x100000a9  /* deprecated alias for hpmute_grave */
#define XK_mute_asciicircum          0x100000aa  /* deprecated alias for hpmute_asciicircum */
#define XK_mute_diaeresis            0x100000ab  /* deprecated alias for hpmute_diaeresis */
#define XK_mute_asciitilde           0x100000ac  /* deprecated alias for hpmute_asciitilde */
#define XK_lira                      0x100000af  /* deprecated alias for hplira */
#define XK_guilder                   0x100000be  /* deprecated alias for hpguilder */
#ifndef XK_Ydiaeresis
#define XK_Ydiaeresis                0x100000ee  /* deprecated */
#endif
#define XK_IO                        0x100000ee  /* deprecated alias for hpYdiaeresis */
#define XK_longminus                 0x100000f6  /* deprecated alias for hplongminus */
#define XK_block                     0x100000fc  /* deprecated alias for hpblock */

#endif /* _HPKEYSYM_H */
