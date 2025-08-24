/*
 * Copyright © 2022 Red Hat, Inc.
 *
 * Permission to use, copy, modify, distribute, and sell this software and its
 * documentation for any purpose is hereby granted without fee, provided that
 * the above copyright notice appear in all copies and that both that copyright
 * notice and this permission notice appear in supporting documentation, and
 * that the name of the copyright holders not be used in advertising or
 * publicity pertaining to distribution of the software without specific,
 * written prior permission.  The copyright holders make no representations
 * about the suitability of this software for any purpose.  It is provided "as
 * is" without express or implied warranty.
 *
 * THE COPYRIGHT HOLDERS DISCLAIM ALL WARRANTIES WITH REGARD TO THIS SOFTWARE,
 * INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS, IN NO
 * EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY SPECIAL, INDIRECT OR
 * CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE,
 * DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
 * TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
 * OF THIS SOFTWARE.
 */

#ifndef _XWAYLAND_PROTO_H_
#define _XWAYLAND_PROTO_H_

#include <X11/Xproto.h>

#define XWAYLAND_EXTENSION_NAME		"XWAYLAND"
#define XWAYLAND_EXTENSION_MAJOR	1
#define XWAYLAND_EXTENSION_MINOR	0

/* Request opcodes */
#define X_XwlQueryVersion		0

#define XwlNumberRequests		1
#define XwlNumberErrors			0
#define XwlNumberEvents			0

typedef struct {
    CARD8   reqType;
    CARD8   xwlReqType;
    CARD16  length;
    CARD16  majorVersion;
    CARD16  minorVersion;
} xXwlQueryVersionReq;
#define sz_xXwlQueryVersionReq		8

typedef struct {
    BYTE    type;   /* X_Reply */
    BYTE    pad1;
    CARD16  sequenceNumber;
    CARD32  length;
    CARD16  majorVersion;
    CARD16  minorVersion;
    CARD32  pad2;
    CARD32  pad3;
    CARD32  pad4;
    CARD32  pad5;
    CARD32  pad6;
} xXwlQueryVersionReply;
#define sz_xXwlQueryVersionReply	32

#endif
