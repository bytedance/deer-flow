/*
 * This file generated automatically from composite.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Composite_API XCB Composite API
 * @brief Composite XCB Protocol Implementation.
 * @{
 **/

#ifndef __COMPOSITE_H
#define __COMPOSITE_H

#include "xcb.h"
#include "xproto.h"
#include "xfixes.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_COMPOSITE_MAJOR_VERSION 0
#define XCB_COMPOSITE_MINOR_VERSION 4

extern xcb_extension_t xcb_composite_id;

typedef enum xcb_composite_redirect_t {
    XCB_COMPOSITE_REDIRECT_AUTOMATIC = 0,
    XCB_COMPOSITE_REDIRECT_MANUAL = 1
} xcb_composite_redirect_t;

/**
 * @brief xcb_composite_query_version_cookie_t
 **/
typedef struct xcb_composite_query_version_cookie_t {
    unsigned int sequence;
} xcb_composite_query_version_cookie_t;

/** Opcode for xcb_composite_query_version. */
#define XCB_COMPOSITE_QUERY_VERSION 0

/**
 * @brief xcb_composite_query_version_request_t
 **/
typedef struct xcb_composite_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t client_major_version;
    uint32_t client_minor_version;
} xcb_composite_query_version_request_t;

/**
 * @brief xcb_composite_query_version_reply_t
 **/
typedef struct xcb_composite_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t major_version;
    uint32_t minor_version;
    uint8_t  pad1[16];
} xcb_composite_query_version_reply_t;

/** Opcode for xcb_composite_redirect_window. */
#define XCB_COMPOSITE_REDIRECT_WINDOW 1

/**
 * @brief xcb_composite_redirect_window_request_t
 **/
typedef struct xcb_composite_redirect_window_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
    uint8_t      update;
    uint8_t      pad0[3];
} xcb_composite_redirect_window_request_t;

/** Opcode for xcb_composite_redirect_subwindows. */
#define XCB_COMPOSITE_REDIRECT_SUBWINDOWS 2

/**
 * @brief xcb_composite_redirect_subwindows_request_t
 **/
typedef struct xcb_composite_redirect_subwindows_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
    uint8_t      update;
    uint8_t      pad0[3];
} xcb_composite_redirect_subwindows_request_t;

/** Opcode for xcb_composite_unredirect_window. */
#define XCB_COMPOSITE_UNREDIRECT_WINDOW 3

/**
 * @brief xcb_composite_unredirect_window_request_t
 **/
typedef struct xcb_composite_unredirect_window_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
    uint8_t      update;
    uint8_t      pad0[3];
} xcb_composite_unredirect_window_request_t;

/** Opcode for xcb_composite_unredirect_subwindows. */
#define XCB_COMPOSITE_UNREDIRECT_SUBWINDOWS 4

/**
 * @brief xcb_composite_unredirect_subwindows_request_t
 **/
typedef struct xcb_composite_unredirect_subwindows_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
    uint8_t      update;
    uint8_t      pad0[3];
} xcb_composite_unredirect_subwindows_request_t;

/** Opcode for xcb_composite_create_region_from_border_clip. */
#define XCB_COMPOSITE_CREATE_REGION_FROM_BORDER_CLIP 5

/**
 * @brief xcb_composite_create_region_from_border_clip_request_t
 **/
typedef struct xcb_composite_create_region_from_border_clip_request_t {
    uint8_t             major_opcode;
    uint8_t             minor_opcode;
    uint16_t            length;
    xcb_xfixes_region_t region;
    xcb_window_t        window;
} xcb_composite_create_region_from_border_clip_request_t;

/** Opcode for xcb_composite_name_window_pixmap. */
#define XCB_COMPOSITE_NAME_WINDOW_PIXMAP 6

/**
 * @brief xcb_composite_name_window_pixmap_request_t
 **/
typedef struct xcb_composite_name_window_pixmap_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
    xcb_pixmap_t pixmap;
} xcb_composite_name_window_pixmap_request_t;

/**
 * @brief xcb_composite_get_overlay_window_cookie_t
 **/
typedef struct xcb_composite_get_overlay_window_cookie_t {
    unsigned int sequence;
} xcb_composite_get_overlay_window_cookie_t;

/** Opcode for xcb_composite_get_overlay_window. */
#define XCB_COMPOSITE_GET_OVERLAY_WINDOW 7

/**
 * @brief xcb_composite_get_overlay_window_request_t
 **/
typedef struct xcb_composite_get_overlay_window_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
} xcb_composite_get_overlay_window_request_t;

/**
 * @brief xcb_composite_get_overlay_window_reply_t
 **/
typedef struct xcb_composite_get_overlay_window_reply_t {
    uint8_t      response_type;
    uint8_t      pad0;
    uint16_t     sequence;
    uint32_t     length;
    xcb_window_t overlay_win;
    uint8_t      pad1[20];
} xcb_composite_get_overlay_window_reply_t;

/** Opcode for xcb_composite_release_overlay_window. */
#define XCB_COMPOSITE_RELEASE_OVERLAY_WINDOW 8

/**
 * @brief xcb_composite_release_overlay_window_request_t
 **/
typedef struct xcb_composite_release_overlay_window_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
} xcb_composite_release_overlay_window_request_t;

/**
 * @brief Negotiate the version of Composite
 *
 * @param c The connection
 * @param client_major_version The major version supported by the client.
 * @param client_minor_version The minor version supported by the client.
 * @return A cookie
 *
 * This negotiates the version of the Composite extension.  It must be precede all
 * other requests using Composite.  Failure to do so will cause a BadRequest error.
 *
 */
xcb_composite_query_version_cookie_t
xcb_composite_query_version (xcb_connection_t *c,
                             uint32_t          client_major_version,
                             uint32_t          client_minor_version);

/**
 * @brief Negotiate the version of Composite
 *
 * @param c The connection
 * @param client_major_version The major version supported by the client.
 * @param client_minor_version The minor version supported by the client.
 * @return A cookie
 *
 * This negotiates the version of the Composite extension.  It must be precede all
 * other requests using Composite.  Failure to do so will cause a BadRequest error.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_composite_query_version_cookie_t
xcb_composite_query_version_unchecked (xcb_connection_t *c,
                                       uint32_t          client_major_version,
                                       uint32_t          client_minor_version);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_composite_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_composite_query_version_reply_t *
xcb_composite_query_version_reply (xcb_connection_t                      *c,
                                   xcb_composite_query_version_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);

/**
 * @brief Redirect the hierarchy starting at "window" to off-screen storage.
 *
 * @param c The connection
 * @param window The root of the hierarchy to redirect to off-screen storage.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update Whether contents are automatically mirrored to the parent window.  If one client
 * 	already specifies an update type of Manual, any attempt by another to specify a
 * 	mode of Manual so will result in an Access error.
 * @return A cookie
 *
 * The hierarchy starting at 'window' is directed to off-screen
 * 	storage.  When all clients enabling redirection terminate,
 * 	the redirection will automatically be disabled.
 * 
 * 	The root window may not be redirected. Doing so results in a Match
 * 	error.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_composite_redirect_window_checked (xcb_connection_t *c,
                                       xcb_window_t      window,
                                       uint8_t           update);

/**
 * @brief Redirect the hierarchy starting at "window" to off-screen storage.
 *
 * @param c The connection
 * @param window The root of the hierarchy to redirect to off-screen storage.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update Whether contents are automatically mirrored to the parent window.  If one client
 * 	already specifies an update type of Manual, any attempt by another to specify a
 * 	mode of Manual so will result in an Access error.
 * @return A cookie
 *
 * The hierarchy starting at 'window' is directed to off-screen
 * 	storage.  When all clients enabling redirection terminate,
 * 	the redirection will automatically be disabled.
 * 
 * 	The root window may not be redirected. Doing so results in a Match
 * 	error.
 *
 */
xcb_void_cookie_t
xcb_composite_redirect_window (xcb_connection_t *c,
                               xcb_window_t      window,
                               uint8_t           update);

/**
 * @brief Redirect all current and future children of ‘window’
 *
 * @param c The connection
 * @param window The root of the hierarchy to redirect to off-screen storage.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update Whether contents are automatically mirrored to the parent window.  If one client
 * 	already specifies an update type of Manual, any attempt by another to specify a
 * 	mode of Manual so will result in an Access error.
 * @return A cookie
 *
 * Hierarchies starting at all current and future children of window
 * 	will be redirected as in RedirectWindow. If update is Manual,
 * 	then painting of the window background during window manipulation
 * 	and ClearArea requests is inhibited.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_composite_redirect_subwindows_checked (xcb_connection_t *c,
                                           xcb_window_t      window,
                                           uint8_t           update);

/**
 * @brief Redirect all current and future children of ‘window’
 *
 * @param c The connection
 * @param window The root of the hierarchy to redirect to off-screen storage.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update Whether contents are automatically mirrored to the parent window.  If one client
 * 	already specifies an update type of Manual, any attempt by another to specify a
 * 	mode of Manual so will result in an Access error.
 * @return A cookie
 *
 * Hierarchies starting at all current and future children of window
 * 	will be redirected as in RedirectWindow. If update is Manual,
 * 	then painting of the window background during window manipulation
 * 	and ClearArea requests is inhibited.
 *
 */
xcb_void_cookie_t
xcb_composite_redirect_subwindows (xcb_connection_t *c,
                                   xcb_window_t      window,
                                   uint8_t           update);

/**
 * @brief Terminate redirection of the specified window.
 *
 * @param c The connection
 * @param window The window to terminate redirection of.  Must be redirected by the
 * 	current client, or a Value error results.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update The update type passed to RedirectWindows.  If this does not match the
 * 	previously requested update type, a Value error results.
 * @return A cookie
 *
 * Redirection of the specified window will be terminated.  This cannot be
 * 	used if the window was redirected with RedirectSubwindows.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_composite_unredirect_window_checked (xcb_connection_t *c,
                                         xcb_window_t      window,
                                         uint8_t           update);

/**
 * @brief Terminate redirection of the specified window.
 *
 * @param c The connection
 * @param window The window to terminate redirection of.  Must be redirected by the
 * 	current client, or a Value error results.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update The update type passed to RedirectWindows.  If this does not match the
 * 	previously requested update type, a Value error results.
 * @return A cookie
 *
 * Redirection of the specified window will be terminated.  This cannot be
 * 	used if the window was redirected with RedirectSubwindows.
 *
 */
xcb_void_cookie_t
xcb_composite_unredirect_window (xcb_connection_t *c,
                                 xcb_window_t      window,
                                 uint8_t           update);

/**
 * @brief Terminate redirection of the specified window’s children
 *
 * @param c The connection
 * @param window The window to terminate redirection of.  Must have previously been
 * 	selected for sub-redirection by the current client, or a Value error
 * 	results.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update The update type passed to RedirectSubWindows.  If this does not match
 * 	the previously requested update type, a Value error results.
 * @return A cookie
 *
 * Redirection of all children of window will be terminated.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_composite_unredirect_subwindows_checked (xcb_connection_t *c,
                                             xcb_window_t      window,
                                             uint8_t           update);

/**
 * @brief Terminate redirection of the specified window’s children
 *
 * @param c The connection
 * @param window The window to terminate redirection of.  Must have previously been
 * 	selected for sub-redirection by the current client, or a Value error
 * 	results.
 * @param update A bitmask of #xcb_composite_redirect_t values.
 * @param update The update type passed to RedirectSubWindows.  If this does not match
 * 	the previously requested update type, a Value error results.
 * @return A cookie
 *
 * Redirection of all children of window will be terminated.
 *
 */
xcb_void_cookie_t
xcb_composite_unredirect_subwindows (xcb_connection_t *c,
                                     xcb_window_t      window,
                                     uint8_t           update);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_composite_create_region_from_border_clip_checked (xcb_connection_t    *c,
                                                      xcb_xfixes_region_t  region,
                                                      xcb_window_t         window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_composite_create_region_from_border_clip (xcb_connection_t    *c,
                                              xcb_xfixes_region_t  region,
                                              xcb_window_t         window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_composite_name_window_pixmap_checked (xcb_connection_t *c,
                                          xcb_window_t      window,
                                          xcb_pixmap_t      pixmap);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_composite_name_window_pixmap (xcb_connection_t *c,
                                  xcb_window_t      window,
                                  xcb_pixmap_t      pixmap);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_composite_get_overlay_window_cookie_t
xcb_composite_get_overlay_window (xcb_connection_t *c,
                                  xcb_window_t      window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_composite_get_overlay_window_cookie_t
xcb_composite_get_overlay_window_unchecked (xcb_connection_t *c,
                                            xcb_window_t      window);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_composite_get_overlay_window_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_composite_get_overlay_window_reply_t *
xcb_composite_get_overlay_window_reply (xcb_connection_t                           *c,
                                        xcb_composite_get_overlay_window_cookie_t   cookie  /**< */,
                                        xcb_generic_error_t                       **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_composite_release_overlay_window_checked (xcb_connection_t *c,
                                              xcb_window_t      window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_composite_release_overlay_window (xcb_connection_t *c,
                                      xcb_window_t      window);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
