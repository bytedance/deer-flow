/*

Copyright 1988, 1998  The Open Group

Permission to use, copy, modify, distribute, and sell this software and its
documentation for any purpose is hereby granted without fee, provided that
the above copyright notice appear in all copies and that both that
copyright notice and this permission notice appear in supporting
documentation.

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
OPEN GROUP BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN
AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Except as contained in this notice, the name of The Open Group shall not be
used in advertising or otherwise to promote the sale, use or other dealings
in this Software without prior written authorization from The Open Group.

*/

#ifndef _Xauth_h
#define _Xauth_h

/* struct xauth is full of implicit padding to properly align the pointers
   after the length fields.   We can't clean that up without breaking ABI,
   so tell clang not to bother complaining about it. */
#ifdef __clang__
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wpadded"
#endif

typedef struct xauth {
    unsigned short   family;
    unsigned short   address_length;
    char    	    *address;
    unsigned short   number_length;
    char    	    *number;
    unsigned short   name_length;
    char    	    *name;
    unsigned short   data_length;
    char   	    *data;
} Xauth;

#ifdef __clang__
#pragma clang diagnostic pop
#endif

#ifndef _XAUTH_STRUCT_ONLY

# include   <X11/Xfuncproto.h>
# include   <X11/Xfuncs.h>

# include   <stdio.h>

# define FamilyLocal (256)	/* not part of X standard (i.e. X.h) */
# define FamilyWild  (65535)
# define FamilyNetname    (254)   /* not part of X standard */
# define FamilyKrb5Principal (253) /* Kerberos 5 principal name */
# define FamilyLocalHost (252)	/* for local non-net authentication */


_XFUNCPROTOBEGIN

#ifndef __has_attribute
# define __has_attribute(x) 0  /* Compatibility with older compilers */
#endif

#if __has_attribute(access)
# define XAU_ACCESS_ATTRIBUTE(X) __attribute__((access X))
#else
# define XAU_ACCESS_ATTRIBUTE(X)
#endif

#if __has_attribute(malloc)
# if defined(__clang__) || (defined(__GNUC__) && __GNUC__ < 11)
/* Clang or gcc do not support the optional deallocator argument */
#  define XAU_MALLOC_ATTRIBUTE(X) __attribute__((malloc))
# else
#  define XAU_MALLOC_ATTRIBUTE(X) __attribute__((malloc X))
# endif
#else
# define XAU_MALLOC_ATTRIBUTE(X)
#endif

char *XauFileName(void);

void XauDisposeAuth(
Xauth*		/* auth */
);

XAU_MALLOC_ATTRIBUTE((XauDisposeAuth, 1))
Xauth *XauReadAuth(
FILE*	/* auth_file */
);

XAU_ACCESS_ATTRIBUTE((read_only, 1)) /* file_name */
int XauLockAuth(
_Xconst char*	/* file_name */,
int		/* retries */,
int		/* timeout */,
long		/* dead */
);

XAU_ACCESS_ATTRIBUTE((read_only, 1)) /* file_name */
int XauUnlockAuth(
_Xconst char*	/* file_name */
);

XAU_ACCESS_ATTRIBUTE((read_only, 2)) /* auth */
int XauWriteAuth(
FILE*		/* auth_file */,
Xauth*		/* auth */
);

XAU_ACCESS_ATTRIBUTE((read_only, 3, 2)) /* address */
XAU_ACCESS_ATTRIBUTE((read_only, 5, 4)) /* number */
XAU_ACCESS_ATTRIBUTE((read_only, 7, 6)) /* name */
Xauth *XauGetAuthByAddr(
#if NeedWidePrototypes
unsigned int	/* family */,
unsigned int	/* address_length */,
#else
unsigned short	/* family */,
unsigned short	/* address_length */,
#endif
_Xconst char*	/* address */,
#if NeedWidePrototypes
unsigned int	/* number_length */,
#else
unsigned short	/* number_length */,
#endif
_Xconst char*	/* number */,
#if NeedWidePrototypes
unsigned int	/* name_length */,
#else
unsigned short	/* name_length */,
#endif
_Xconst char*	/* name */
);

XAU_ACCESS_ATTRIBUTE((read_only, 3, 2)) /* address */
XAU_ACCESS_ATTRIBUTE((read_only, 5, 4)) /* number */
XAU_ACCESS_ATTRIBUTE((read_only, 7, 6)) /* type_names */
XAU_ACCESS_ATTRIBUTE((read_only, 8, 6)) /* type_lengths */
Xauth *XauGetBestAuthByAddr(
#if NeedWidePrototypes
unsigned int	/* family */,
unsigned int	/* address_length */,
#else
unsigned short	/* family */,
unsigned short	/* address_length */,
#endif
_Xconst char*	/* address */,
#if NeedWidePrototypes
unsigned int	/* number_length */,
#else
unsigned short	/* number_length */,
#endif
_Xconst char*	/* number */,
int		/* types_length */,
char**		/* type_names */,
_Xconst int*	/* type_lengths */
);

_XFUNCPROTOEND

/* Return values from XauLockAuth */

# define LOCK_SUCCESS	0	/* lock succeeded */
# define LOCK_ERROR	1	/* lock unexpectedly failed, check errno */
# define LOCK_TIMEOUT	2	/* lock failed, timeouts expired */

#endif /* _XAUTH_STRUCT_ONLY */

#endif /* _Xauth_h */
