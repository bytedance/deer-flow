/*
 * This file generated automatically from screensaver.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_ScreenSaver_API XCB ScreenSaver API
 * @brief ScreenSaver XCB Protocol Implementation.
 * @{
 **/

#ifndef __SCREENSAVER_H
#define __SCREENSAVER_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_SCREENSAVER_MAJOR_VERSION 1
#define XCB_SCREENSAVER_MINOR_VERSION 1

extern xcb_extension_t xcb_screensaver_id;

typedef enum xcb_screensaver_kind_t {
    XCB_SCREENSAVER_KIND_BLANKED = 0,
    XCB_SCREENSAVER_KIND_INTERNAL = 1,
    XCB_SCREENSAVER_KIND_EXTERNAL = 2
} xcb_screensaver_kind_t;

typedef enum xcb_screensaver_event_t {
    XCB_SCREENSAVER_EVENT_NOTIFY_MASK = 1,
    XCB_SCREENSAVER_EVENT_CYCLE_MASK = 2
} xcb_screensaver_event_t;

typedef enum xcb_screensaver_state_t {
    XCB_SCREENSAVER_STATE_OFF = 0,
    XCB_SCREENSAVER_STATE_ON = 1,
    XCB_SCREENSAVER_STATE_CYCLE = 2,
    XCB_SCREENSAVER_STATE_DISABLED = 3
} xcb_screensaver_state_t;

/**
 * @brief xcb_screensaver_query_version_cookie_t
 **/
typedef struct xcb_screensaver_query_version_cookie_t {
    unsigned int sequence;
} xcb_screensaver_query_version_cookie_t;

/** Opcode for xcb_screensaver_query_version. */
#define XCB_SCREENSAVER_QUERY_VERSION 0

/**
 * @brief xcb_screensaver_query_version_request_t
 **/
typedef struct xcb_screensaver_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  client_major_version;
    uint8_t  client_minor_version;
    uint8_t  pad0[2];
} xcb_screensaver_query_version_request_t;

/**
 * @brief xcb_screensaver_query_version_reply_t
 **/
typedef struct xcb_screensaver_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t server_major_version;
    uint16_t server_minor_version;
    uint8_t  pad1[20];
} xcb_screensaver_query_version_reply_t;

/**
 * @brief xcb_screensaver_query_info_cookie_t
 **/
typedef struct xcb_screensaver_query_info_cookie_t {
    unsigned int sequence;
} xcb_screensaver_query_info_cookie_t;

/** Opcode for xcb_screensaver_query_info. */
#define XCB_SCREENSAVER_QUERY_INFO 1

/**
 * @brief xcb_screensaver_query_info_request_t
 **/
typedef struct xcb_screensaver_query_info_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_drawable_t drawable;
} xcb_screensaver_query_info_request_t;

/**
 * @brief xcb_screensaver_query_info_reply_t
 **/
typedef struct xcb_screensaver_query_info_reply_t {
    uint8_t      response_type;
    uint8_t      state;
    uint16_t     sequence;
    uint32_t     length;
    xcb_window_t saver_window;
    uint32_t     ms_until_server;
    uint32_t     ms_since_user_input;
    uint32_t     event_mask;
    uint8_t      kind;
    uint8_t      pad0[7];
} xcb_screensaver_query_info_reply_t;

/** Opcode for xcb_screensaver_select_input. */
#define XCB_SCREENSAVER_SELECT_INPUT 2

/**
 * @brief xcb_screensaver_select_input_request_t
 **/
typedef struct xcb_screensaver_select_input_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_drawable_t drawable;
    uint32_t       event_mask;
} xcb_screensaver_select_input_request_t;

/**
 * @brief xcb_screensaver_set_attributes_value_list_t
 **/
typedef struct xcb_screensaver_set_attributes_value_list_t {
    xcb_pixmap_t   background_pixmap;
    uint32_t       background_pixel;
    xcb_pixmap_t   border_pixmap;
    uint32_t       border_pixel;
    uint32_t       bit_gravity;
    uint32_t       win_gravity;
    uint32_t       backing_store;
    uint32_t       backing_planes;
    uint32_t       backing_pixel;
    xcb_bool32_t   override_redirect;
    xcb_bool32_t   save_under;
    uint32_t       event_mask;
    uint32_t       do_not_propogate_mask;
    xcb_colormap_t colormap;
    xcb_cursor_t   cursor;
} xcb_screensaver_set_attributes_value_list_t;

/** Opcode for xcb_screensaver_set_attributes. */
#define XCB_SCREENSAVER_SET_ATTRIBUTES 3

/**
 * @brief xcb_screensaver_set_attributes_request_t
 **/
typedef struct xcb_screensaver_set_attributes_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_drawable_t drawable;
    int16_t        x;
    int16_t        y;
    uint16_t       width;
    uint16_t       height;
    uint16_t       border_width;
    uint8_t        _class;
    uint8_t        depth;
    xcb_visualid_t visual;
    uint32_t       value_mask;
} xcb_screensaver_set_attributes_request_t;

/** Opcode for xcb_screensaver_unset_attributes. */
#define XCB_SCREENSAVER_UNSET_ATTRIBUTES 4

/**
 * @brief xcb_screensaver_unset_attributes_request_t
 **/
typedef struct xcb_screensaver_unset_attributes_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_drawable_t drawable;
} xcb_screensaver_unset_attributes_request_t;

/** Opcode for xcb_screensaver_suspend. */
#define XCB_SCREENSAVER_SUSPEND 5

/**
 * @brief xcb_screensaver_suspend_request_t
 **/
typedef struct xcb_screensaver_suspend_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t suspend;
} xcb_screensaver_suspend_request_t;

/** Opcode for xcb_screensaver_notify. */
#define XCB_SCREENSAVER_NOTIFY 0

/**
 * @brief xcb_screensaver_notify_event_t
 **/
typedef struct xcb_screensaver_notify_event_t {
    uint8_t         response_type;
    uint8_t         state;
    uint16_t        sequence;
    xcb_timestamp_t time;
    xcb_window_t    root;
    xcb_window_t    window;
    uint8_t         kind;
    uint8_t         forced;
    uint8_t         pad0[14];
} xcb_screensaver_notify_event_t;

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_screensaver_query_version_cookie_t
xcb_screensaver_query_version (xcb_connection_t *c,
                               uint8_t           client_major_version,
                               uint8_t           client_minor_version);

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
xcb_screensaver_query_version_cookie_t
xcb_screensaver_query_version_unchecked (xcb_connection_t *c,
                                         uint8_t           client_major_version,
                                         uint8_t           client_minor_version);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_screensaver_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_screensaver_query_version_reply_t *
xcb_screensaver_query_version_reply (xcb_connection_t                        *c,
                                     xcb_screensaver_query_version_cookie_t   cookie  /**< */,
                                     xcb_generic_error_t                    **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_screensaver_query_info_cookie_t
xcb_screensaver_query_info (xcb_connection_t *c,
                            xcb_drawable_t    drawable);

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
xcb_screensaver_query_info_cookie_t
xcb_screensaver_query_info_unchecked (xcb_connection_t *c,
                                      xcb_drawable_t    drawable);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_screensaver_query_info_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_screensaver_query_info_reply_t *
xcb_screensaver_query_info_reply (xcb_connection_t                     *c,
                                  xcb_screensaver_query_info_cookie_t   cookie  /**< */,
                                  xcb_generic_error_t                 **e);

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
xcb_screensaver_select_input_checked (xcb_connection_t *c,
                                      xcb_drawable_t    drawable,
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
xcb_screensaver_select_input (xcb_connection_t *c,
                              xcb_drawable_t    drawable,
                              uint32_t          event_mask);

int
xcb_screensaver_set_attributes_value_list_serialize (void                                              **_buffer,
                                                     uint32_t                                            value_mask,
                                                     const xcb_screensaver_set_attributes_value_list_t  *_aux);

int
xcb_screensaver_set_attributes_value_list_unpack (const void                                   *_buffer,
                                                  uint32_t                                      value_mask,
                                                  xcb_screensaver_set_attributes_value_list_t  *_aux);

int
xcb_screensaver_set_attributes_value_list_sizeof (const void  *_buffer,
                                                  uint32_t     value_mask);

int
xcb_screensaver_set_attributes_sizeof (const void  *_buffer);

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
xcb_screensaver_set_attributes_checked (xcb_connection_t *c,
                                        xcb_drawable_t    drawable,
                                        int16_t           x,
                                        int16_t           y,
                                        uint16_t          width,
                                        uint16_t          height,
                                        uint16_t          border_width,
                                        uint8_t           _class,
                                        uint8_t           depth,
                                        xcb_visualid_t    visual,
                                        uint32_t          value_mask,
                                        const void       *value_list);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_screensaver_set_attributes (xcb_connection_t *c,
                                xcb_drawable_t    drawable,
                                int16_t           x,
                                int16_t           y,
                                uint16_t          width,
                                uint16_t          height,
                                uint16_t          border_width,
                                uint8_t           _class,
                                uint8_t           depth,
                                xcb_visualid_t    visual,
                                uint32_t          value_mask,
                                const void       *value_list);

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
xcb_screensaver_set_attributes_aux_checked (xcb_connection_t                                  *c,
                                            xcb_drawable_t                                     drawable,
                                            int16_t                                            x,
                                            int16_t                                            y,
                                            uint16_t                                           width,
                                            uint16_t                                           height,
                                            uint16_t                                           border_width,
                                            uint8_t                                            _class,
                                            uint8_t                                            depth,
                                            xcb_visualid_t                                     visual,
                                            uint32_t                                           value_mask,
                                            const xcb_screensaver_set_attributes_value_list_t *value_list);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_screensaver_set_attributes_aux (xcb_connection_t                                  *c,
                                    xcb_drawable_t                                     drawable,
                                    int16_t                                            x,
                                    int16_t                                            y,
                                    uint16_t                                           width,
                                    uint16_t                                           height,
                                    uint16_t                                           border_width,
                                    uint8_t                                            _class,
                                    uint8_t                                            depth,
                                    xcb_visualid_t                                     visual,
                                    uint32_t                                           value_mask,
                                    const xcb_screensaver_set_attributes_value_list_t *value_list);

void *
xcb_screensaver_set_attributes_value_list (const xcb_screensaver_set_attributes_request_t *R);

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
xcb_screensaver_unset_attributes_checked (xcb_connection_t *c,
                                          xcb_drawable_t    drawable);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_screensaver_unset_attributes (xcb_connection_t *c,
                                  xcb_drawable_t    drawable);

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
xcb_screensaver_suspend_checked (xcb_connection_t *c,
                                 uint32_t          suspend);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_screensaver_suspend (xcb_connection_t *c,
                         uint32_t          suspend);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
