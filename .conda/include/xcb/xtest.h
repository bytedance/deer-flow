/*
 * This file generated automatically from xtest.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Test_API XCB Test API
 * @brief Test XCB Protocol Implementation.
 * @{
 **/

#ifndef __XTEST_H
#define __XTEST_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_TEST_MAJOR_VERSION 2
#define XCB_TEST_MINOR_VERSION 2

extern xcb_extension_t xcb_test_id;

/**
 * @brief xcb_test_get_version_cookie_t
 **/
typedef struct xcb_test_get_version_cookie_t {
    unsigned int sequence;
} xcb_test_get_version_cookie_t;

/** Opcode for xcb_test_get_version. */
#define XCB_TEST_GET_VERSION 0

/**
 * @brief xcb_test_get_version_request_t
 **/
typedef struct xcb_test_get_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  major_version;
    uint8_t  pad0;
    uint16_t minor_version;
} xcb_test_get_version_request_t;

/**
 * @brief xcb_test_get_version_reply_t
 **/
typedef struct xcb_test_get_version_reply_t {
    uint8_t  response_type;
    uint8_t  major_version;
    uint16_t sequence;
    uint32_t length;
    uint16_t minor_version;
} xcb_test_get_version_reply_t;

typedef enum xcb_test_cursor_t {
    XCB_TEST_CURSOR_NONE = 0,
    XCB_TEST_CURSOR_CURRENT = 1
} xcb_test_cursor_t;

/**
 * @brief xcb_test_compare_cursor_cookie_t
 **/
typedef struct xcb_test_compare_cursor_cookie_t {
    unsigned int sequence;
} xcb_test_compare_cursor_cookie_t;

/** Opcode for xcb_test_compare_cursor. */
#define XCB_TEST_COMPARE_CURSOR 1

/**
 * @brief xcb_test_compare_cursor_request_t
 **/
typedef struct xcb_test_compare_cursor_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
    xcb_cursor_t cursor;
} xcb_test_compare_cursor_request_t;

/**
 * @brief xcb_test_compare_cursor_reply_t
 **/
typedef struct xcb_test_compare_cursor_reply_t {
    uint8_t  response_type;
    uint8_t  same;
    uint16_t sequence;
    uint32_t length;
} xcb_test_compare_cursor_reply_t;

/** Opcode for xcb_test_fake_input. */
#define XCB_TEST_FAKE_INPUT 2

/**
 * @brief xcb_test_fake_input_request_t
 **/
typedef struct xcb_test_fake_input_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    uint8_t      type;
    uint8_t      detail;
    uint8_t      pad0[2];
    uint32_t     time;
    xcb_window_t root;
    uint8_t      pad1[8];
    int16_t      rootX;
    int16_t      rootY;
    uint8_t      pad2[7];
    uint8_t      deviceid;
} xcb_test_fake_input_request_t;

/** Opcode for xcb_test_grab_control. */
#define XCB_TEST_GRAB_CONTROL 3

/**
 * @brief xcb_test_grab_control_request_t
 **/
typedef struct xcb_test_grab_control_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  impervious;
    uint8_t  pad0[3];
} xcb_test_grab_control_request_t;

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_test_get_version_cookie_t
xcb_test_get_version (xcb_connection_t *c,
                      uint8_t           major_version,
                      uint16_t          minor_version);

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
xcb_test_get_version_cookie_t
xcb_test_get_version_unchecked (xcb_connection_t *c,
                                uint8_t           major_version,
                                uint16_t          minor_version);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_test_get_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_test_get_version_reply_t *
xcb_test_get_version_reply (xcb_connection_t               *c,
                            xcb_test_get_version_cookie_t   cookie  /**< */,
                            xcb_generic_error_t           **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_test_compare_cursor_cookie_t
xcb_test_compare_cursor (xcb_connection_t *c,
                         xcb_window_t      window,
                         xcb_cursor_t      cursor);

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
xcb_test_compare_cursor_cookie_t
xcb_test_compare_cursor_unchecked (xcb_connection_t *c,
                                   xcb_window_t      window,
                                   xcb_cursor_t      cursor);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_test_compare_cursor_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_test_compare_cursor_reply_t *
xcb_test_compare_cursor_reply (xcb_connection_t                  *c,
                               xcb_test_compare_cursor_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

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
xcb_test_fake_input_checked (xcb_connection_t *c,
                             uint8_t           type,
                             uint8_t           detail,
                             uint32_t          time,
                             xcb_window_t      root,
                             int16_t           rootX,
                             int16_t           rootY,
                             uint8_t           deviceid);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_test_fake_input (xcb_connection_t *c,
                     uint8_t           type,
                     uint8_t           detail,
                     uint32_t          time,
                     xcb_window_t      root,
                     int16_t           rootX,
                     int16_t           rootY,
                     uint8_t           deviceid);

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
xcb_test_grab_control_checked (xcb_connection_t *c,
                               uint8_t           impervious);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_test_grab_control (xcb_connection_t *c,
                       uint8_t           impervious);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
