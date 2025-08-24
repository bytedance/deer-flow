/*
 * This file generated automatically from xinerama.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Xinerama_API XCB Xinerama API
 * @brief Xinerama XCB Protocol Implementation.
 * @{
 **/

#ifndef __XINERAMA_H
#define __XINERAMA_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_XINERAMA_MAJOR_VERSION 1
#define XCB_XINERAMA_MINOR_VERSION 1

extern xcb_extension_t xcb_xinerama_id;

/**
 * @brief xcb_xinerama_screen_info_t
 **/
typedef struct xcb_xinerama_screen_info_t {
    int16_t  x_org;
    int16_t  y_org;
    uint16_t width;
    uint16_t height;
} xcb_xinerama_screen_info_t;

/**
 * @brief xcb_xinerama_screen_info_iterator_t
 **/
typedef struct xcb_xinerama_screen_info_iterator_t {
    xcb_xinerama_screen_info_t *data;
    int                         rem;
    int                         index;
} xcb_xinerama_screen_info_iterator_t;

/**
 * @brief xcb_xinerama_query_version_cookie_t
 **/
typedef struct xcb_xinerama_query_version_cookie_t {
    unsigned int sequence;
} xcb_xinerama_query_version_cookie_t;

/** Opcode for xcb_xinerama_query_version. */
#define XCB_XINERAMA_QUERY_VERSION 0

/**
 * @brief xcb_xinerama_query_version_request_t
 **/
typedef struct xcb_xinerama_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  major;
    uint8_t  minor;
} xcb_xinerama_query_version_request_t;

/**
 * @brief xcb_xinerama_query_version_reply_t
 **/
typedef struct xcb_xinerama_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t major;
    uint16_t minor;
} xcb_xinerama_query_version_reply_t;

/**
 * @brief xcb_xinerama_get_state_cookie_t
 **/
typedef struct xcb_xinerama_get_state_cookie_t {
    unsigned int sequence;
} xcb_xinerama_get_state_cookie_t;

/** Opcode for xcb_xinerama_get_state. */
#define XCB_XINERAMA_GET_STATE 1

/**
 * @brief xcb_xinerama_get_state_request_t
 **/
typedef struct xcb_xinerama_get_state_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
} xcb_xinerama_get_state_request_t;

/**
 * @brief xcb_xinerama_get_state_reply_t
 **/
typedef struct xcb_xinerama_get_state_reply_t {
    uint8_t      response_type;
    uint8_t      state;
    uint16_t     sequence;
    uint32_t     length;
    xcb_window_t window;
} xcb_xinerama_get_state_reply_t;

/**
 * @brief xcb_xinerama_get_screen_count_cookie_t
 **/
typedef struct xcb_xinerama_get_screen_count_cookie_t {
    unsigned int sequence;
} xcb_xinerama_get_screen_count_cookie_t;

/** Opcode for xcb_xinerama_get_screen_count. */
#define XCB_XINERAMA_GET_SCREEN_COUNT 2

/**
 * @brief xcb_xinerama_get_screen_count_request_t
 **/
typedef struct xcb_xinerama_get_screen_count_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
} xcb_xinerama_get_screen_count_request_t;

/**
 * @brief xcb_xinerama_get_screen_count_reply_t
 **/
typedef struct xcb_xinerama_get_screen_count_reply_t {
    uint8_t      response_type;
    uint8_t      screen_count;
    uint16_t     sequence;
    uint32_t     length;
    xcb_window_t window;
} xcb_xinerama_get_screen_count_reply_t;

/**
 * @brief xcb_xinerama_get_screen_size_cookie_t
 **/
typedef struct xcb_xinerama_get_screen_size_cookie_t {
    unsigned int sequence;
} xcb_xinerama_get_screen_size_cookie_t;

/** Opcode for xcb_xinerama_get_screen_size. */
#define XCB_XINERAMA_GET_SCREEN_SIZE 3

/**
 * @brief xcb_xinerama_get_screen_size_request_t
 **/
typedef struct xcb_xinerama_get_screen_size_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
    uint32_t     screen;
} xcb_xinerama_get_screen_size_request_t;

/**
 * @brief xcb_xinerama_get_screen_size_reply_t
 **/
typedef struct xcb_xinerama_get_screen_size_reply_t {
    uint8_t      response_type;
    uint8_t      pad0;
    uint16_t     sequence;
    uint32_t     length;
    uint32_t     width;
    uint32_t     height;
    xcb_window_t window;
    uint32_t     screen;
} xcb_xinerama_get_screen_size_reply_t;

/**
 * @brief xcb_xinerama_is_active_cookie_t
 **/
typedef struct xcb_xinerama_is_active_cookie_t {
    unsigned int sequence;
} xcb_xinerama_is_active_cookie_t;

/** Opcode for xcb_xinerama_is_active. */
#define XCB_XINERAMA_IS_ACTIVE 4

/**
 * @brief xcb_xinerama_is_active_request_t
 **/
typedef struct xcb_xinerama_is_active_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_xinerama_is_active_request_t;

/**
 * @brief xcb_xinerama_is_active_reply_t
 **/
typedef struct xcb_xinerama_is_active_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t state;
} xcb_xinerama_is_active_reply_t;

/**
 * @brief xcb_xinerama_query_screens_cookie_t
 **/
typedef struct xcb_xinerama_query_screens_cookie_t {
    unsigned int sequence;
} xcb_xinerama_query_screens_cookie_t;

/** Opcode for xcb_xinerama_query_screens. */
#define XCB_XINERAMA_QUERY_SCREENS 5

/**
 * @brief xcb_xinerama_query_screens_request_t
 **/
typedef struct xcb_xinerama_query_screens_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_xinerama_query_screens_request_t;

/**
 * @brief xcb_xinerama_query_screens_reply_t
 **/
typedef struct xcb_xinerama_query_screens_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t number;
    uint8_t  pad1[20];
} xcb_xinerama_query_screens_reply_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xinerama_screen_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xinerama_screen_info_t)
 */
void
xcb_xinerama_screen_info_next (xcb_xinerama_screen_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xinerama_screen_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xinerama_screen_info_end (xcb_xinerama_screen_info_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xinerama_query_version_cookie_t
xcb_xinerama_query_version (xcb_connection_t *c,
                            uint8_t           major,
                            uint8_t           minor);

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
xcb_xinerama_query_version_cookie_t
xcb_xinerama_query_version_unchecked (xcb_connection_t *c,
                                      uint8_t           major,
                                      uint8_t           minor);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xinerama_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xinerama_query_version_reply_t *
xcb_xinerama_query_version_reply (xcb_connection_t                     *c,
                                  xcb_xinerama_query_version_cookie_t   cookie  /**< */,
                                  xcb_generic_error_t                 **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xinerama_get_state_cookie_t
xcb_xinerama_get_state (xcb_connection_t *c,
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
xcb_xinerama_get_state_cookie_t
xcb_xinerama_get_state_unchecked (xcb_connection_t *c,
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
 * xcb_xinerama_get_state_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xinerama_get_state_reply_t *
xcb_xinerama_get_state_reply (xcb_connection_t                 *c,
                              xcb_xinerama_get_state_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xinerama_get_screen_count_cookie_t
xcb_xinerama_get_screen_count (xcb_connection_t *c,
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
xcb_xinerama_get_screen_count_cookie_t
xcb_xinerama_get_screen_count_unchecked (xcb_connection_t *c,
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
 * xcb_xinerama_get_screen_count_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xinerama_get_screen_count_reply_t *
xcb_xinerama_get_screen_count_reply (xcb_connection_t                        *c,
                                     xcb_xinerama_get_screen_count_cookie_t   cookie  /**< */,
                                     xcb_generic_error_t                    **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xinerama_get_screen_size_cookie_t
xcb_xinerama_get_screen_size (xcb_connection_t *c,
                              xcb_window_t      window,
                              uint32_t          screen);

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
xcb_xinerama_get_screen_size_cookie_t
xcb_xinerama_get_screen_size_unchecked (xcb_connection_t *c,
                                        xcb_window_t      window,
                                        uint32_t          screen);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xinerama_get_screen_size_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xinerama_get_screen_size_reply_t *
xcb_xinerama_get_screen_size_reply (xcb_connection_t                       *c,
                                    xcb_xinerama_get_screen_size_cookie_t   cookie  /**< */,
                                    xcb_generic_error_t                   **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xinerama_is_active_cookie_t
xcb_xinerama_is_active (xcb_connection_t *c);

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
xcb_xinerama_is_active_cookie_t
xcb_xinerama_is_active_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xinerama_is_active_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xinerama_is_active_reply_t *
xcb_xinerama_is_active_reply (xcb_connection_t                 *c,
                              xcb_xinerama_is_active_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

int
xcb_xinerama_query_screens_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xinerama_query_screens_cookie_t
xcb_xinerama_query_screens (xcb_connection_t *c);

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
xcb_xinerama_query_screens_cookie_t
xcb_xinerama_query_screens_unchecked (xcb_connection_t *c);

xcb_xinerama_screen_info_t *
xcb_xinerama_query_screens_screen_info (const xcb_xinerama_query_screens_reply_t *R);

int
xcb_xinerama_query_screens_screen_info_length (const xcb_xinerama_query_screens_reply_t *R);

xcb_xinerama_screen_info_iterator_t
xcb_xinerama_query_screens_screen_info_iterator (const xcb_xinerama_query_screens_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xinerama_query_screens_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xinerama_query_screens_reply_t *
xcb_xinerama_query_screens_reply (xcb_connection_t                     *c,
                                  xcb_xinerama_query_screens_cookie_t   cookie  /**< */,
                                  xcb_generic_error_t                 **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
