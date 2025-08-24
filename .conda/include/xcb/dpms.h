/*
 * This file generated automatically from dpms.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_DPMS_API XCB DPMS API
 * @brief DPMS XCB Protocol Implementation.
 * @{
 **/

#ifndef __DPMS_H
#define __DPMS_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_DPMS_MAJOR_VERSION 1
#define XCB_DPMS_MINOR_VERSION 2

extern xcb_extension_t xcb_dpms_id;

/**
 * @brief xcb_dpms_get_version_cookie_t
 **/
typedef struct xcb_dpms_get_version_cookie_t {
    unsigned int sequence;
} xcb_dpms_get_version_cookie_t;

/** Opcode for xcb_dpms_get_version. */
#define XCB_DPMS_GET_VERSION 0

/**
 * @brief xcb_dpms_get_version_request_t
 **/
typedef struct xcb_dpms_get_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t client_major_version;
    uint16_t client_minor_version;
} xcb_dpms_get_version_request_t;

/**
 * @brief xcb_dpms_get_version_reply_t
 **/
typedef struct xcb_dpms_get_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t server_major_version;
    uint16_t server_minor_version;
} xcb_dpms_get_version_reply_t;

/**
 * @brief xcb_dpms_capable_cookie_t
 **/
typedef struct xcb_dpms_capable_cookie_t {
    unsigned int sequence;
} xcb_dpms_capable_cookie_t;

/** Opcode for xcb_dpms_capable. */
#define XCB_DPMS_CAPABLE 1

/**
 * @brief xcb_dpms_capable_request_t
 **/
typedef struct xcb_dpms_capable_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_dpms_capable_request_t;

/**
 * @brief xcb_dpms_capable_reply_t
 **/
typedef struct xcb_dpms_capable_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  capable;
    uint8_t  pad1[23];
} xcb_dpms_capable_reply_t;

/**
 * @brief xcb_dpms_get_timeouts_cookie_t
 **/
typedef struct xcb_dpms_get_timeouts_cookie_t {
    unsigned int sequence;
} xcb_dpms_get_timeouts_cookie_t;

/** Opcode for xcb_dpms_get_timeouts. */
#define XCB_DPMS_GET_TIMEOUTS 2

/**
 * @brief xcb_dpms_get_timeouts_request_t
 **/
typedef struct xcb_dpms_get_timeouts_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_dpms_get_timeouts_request_t;

/**
 * @brief xcb_dpms_get_timeouts_reply_t
 **/
typedef struct xcb_dpms_get_timeouts_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t standby_timeout;
    uint16_t suspend_timeout;
    uint16_t off_timeout;
    uint8_t  pad1[18];
} xcb_dpms_get_timeouts_reply_t;

/** Opcode for xcb_dpms_set_timeouts. */
#define XCB_DPMS_SET_TIMEOUTS 3

/**
 * @brief xcb_dpms_set_timeouts_request_t
 **/
typedef struct xcb_dpms_set_timeouts_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t standby_timeout;
    uint16_t suspend_timeout;
    uint16_t off_timeout;
} xcb_dpms_set_timeouts_request_t;

/** Opcode for xcb_dpms_enable. */
#define XCB_DPMS_ENABLE 4

/**
 * @brief xcb_dpms_enable_request_t
 **/
typedef struct xcb_dpms_enable_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_dpms_enable_request_t;

/** Opcode for xcb_dpms_disable. */
#define XCB_DPMS_DISABLE 5

/**
 * @brief xcb_dpms_disable_request_t
 **/
typedef struct xcb_dpms_disable_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_dpms_disable_request_t;

typedef enum xcb_dpms_dpms_mode_t {
    XCB_DPMS_DPMS_MODE_ON = 0,
    XCB_DPMS_DPMS_MODE_STANDBY = 1,
    XCB_DPMS_DPMS_MODE_SUSPEND = 2,
    XCB_DPMS_DPMS_MODE_OFF = 3
} xcb_dpms_dpms_mode_t;

/** Opcode for xcb_dpms_force_level. */
#define XCB_DPMS_FORCE_LEVEL 6

/**
 * @brief xcb_dpms_force_level_request_t
 **/
typedef struct xcb_dpms_force_level_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t power_level;
} xcb_dpms_force_level_request_t;

/**
 * @brief xcb_dpms_info_cookie_t
 **/
typedef struct xcb_dpms_info_cookie_t {
    unsigned int sequence;
} xcb_dpms_info_cookie_t;

/** Opcode for xcb_dpms_info. */
#define XCB_DPMS_INFO 7

/**
 * @brief xcb_dpms_info_request_t
 **/
typedef struct xcb_dpms_info_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_dpms_info_request_t;

/**
 * @brief xcb_dpms_info_reply_t
 **/
typedef struct xcb_dpms_info_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t power_level;
    uint8_t  state;
    uint8_t  pad1[21];
} xcb_dpms_info_reply_t;

typedef enum xcb_dpms_event_mask_t {
    XCB_DPMS_EVENT_MASK_INFO_NOTIFY = 1
} xcb_dpms_event_mask_t;

/** Opcode for xcb_dpms_select_input. */
#define XCB_DPMS_SELECT_INPUT 8

/**
 * @brief xcb_dpms_select_input_request_t
 **/
typedef struct xcb_dpms_select_input_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t event_mask;
} xcb_dpms_select_input_request_t;

/** Opcode for xcb_dpms_info_notify. */
#define XCB_DPMS_INFO_NOTIFY 0

/**
 * @brief xcb_dpms_info_notify_event_t
 **/
typedef struct xcb_dpms_info_notify_event_t {
    uint8_t         response_type;
    uint8_t         extension;
    uint16_t        sequence;
    uint32_t        length;
    uint16_t        event_type;
    uint8_t         pad0[2];
    xcb_timestamp_t timestamp;
    uint16_t        power_level;
    uint8_t         state;
    uint8_t         pad1[21];
} xcb_dpms_info_notify_event_t;

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_dpms_get_version_cookie_t
xcb_dpms_get_version (xcb_connection_t *c,
                      uint16_t          client_major_version,
                      uint16_t          client_minor_version);

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
xcb_dpms_get_version_cookie_t
xcb_dpms_get_version_unchecked (xcb_connection_t *c,
                                uint16_t          client_major_version,
                                uint16_t          client_minor_version);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_dpms_get_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_dpms_get_version_reply_t *
xcb_dpms_get_version_reply (xcb_connection_t               *c,
                            xcb_dpms_get_version_cookie_t   cookie  /**< */,
                            xcb_generic_error_t           **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_dpms_capable_cookie_t
xcb_dpms_capable (xcb_connection_t *c);

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
xcb_dpms_capable_cookie_t
xcb_dpms_capable_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_dpms_capable_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_dpms_capable_reply_t *
xcb_dpms_capable_reply (xcb_connection_t           *c,
                        xcb_dpms_capable_cookie_t   cookie  /**< */,
                        xcb_generic_error_t       **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_dpms_get_timeouts_cookie_t
xcb_dpms_get_timeouts (xcb_connection_t *c);

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
xcb_dpms_get_timeouts_cookie_t
xcb_dpms_get_timeouts_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_dpms_get_timeouts_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_dpms_get_timeouts_reply_t *
xcb_dpms_get_timeouts_reply (xcb_connection_t                *c,
                             xcb_dpms_get_timeouts_cookie_t   cookie  /**< */,
                             xcb_generic_error_t            **e);

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
xcb_dpms_set_timeouts_checked (xcb_connection_t *c,
                               uint16_t          standby_timeout,
                               uint16_t          suspend_timeout,
                               uint16_t          off_timeout);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_dpms_set_timeouts (xcb_connection_t *c,
                       uint16_t          standby_timeout,
                       uint16_t          suspend_timeout,
                       uint16_t          off_timeout);

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
xcb_dpms_enable_checked (xcb_connection_t *c);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_dpms_enable (xcb_connection_t *c);

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
xcb_dpms_disable_checked (xcb_connection_t *c);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_dpms_disable (xcb_connection_t *c);

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
xcb_dpms_force_level_checked (xcb_connection_t *c,
                              uint16_t          power_level);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_dpms_force_level (xcb_connection_t *c,
                      uint16_t          power_level);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_dpms_info_cookie_t
xcb_dpms_info (xcb_connection_t *c);

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
xcb_dpms_info_cookie_t
xcb_dpms_info_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_dpms_info_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_dpms_info_reply_t *
xcb_dpms_info_reply (xcb_connection_t        *c,
                     xcb_dpms_info_cookie_t   cookie  /**< */,
                     xcb_generic_error_t    **e);

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
xcb_dpms_select_input_checked (xcb_connection_t *c,
                               uint32_t          event_mask);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_dpms_select_input (xcb_connection_t *c,
                       uint32_t          event_mask);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
