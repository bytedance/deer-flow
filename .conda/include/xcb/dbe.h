/*
 * This file generated automatically from dbe.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Dbe_API XCB Dbe API
 * @brief Dbe XCB Protocol Implementation.
 * @{
 **/

#ifndef __DBE_H
#define __DBE_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_DBE_MAJOR_VERSION 1
#define XCB_DBE_MINOR_VERSION 0

extern xcb_extension_t xcb_dbe_id;

typedef uint32_t xcb_dbe_back_buffer_t;

/**
 * @brief xcb_dbe_back_buffer_iterator_t
 **/
typedef struct xcb_dbe_back_buffer_iterator_t {
    xcb_dbe_back_buffer_t *data;
    int                    rem;
    int                    index;
} xcb_dbe_back_buffer_iterator_t;

typedef enum xcb_dbe_swap_action_t {
    XCB_DBE_SWAP_ACTION_UNDEFINED = 0,
/**< Discard the buffer. The buffer may be reallocated and end up with random VRAM content. */

    XCB_DBE_SWAP_ACTION_BACKGROUND = 1,
/**< Erase with window background. */

    XCB_DBE_SWAP_ACTION_UNTOUCHED = 2,
/**< Leave untouched. */

    XCB_DBE_SWAP_ACTION_COPIED = 3
/**< Copy the newly displayed front buffer. */

} xcb_dbe_swap_action_t;

/**
 * @brief xcb_dbe_swap_info_t
 **/
typedef struct xcb_dbe_swap_info_t {
    xcb_window_t window;
    uint8_t      swap_action;
    uint8_t      pad0[3];
} xcb_dbe_swap_info_t;

/**
 * @brief xcb_dbe_swap_info_iterator_t
 **/
typedef struct xcb_dbe_swap_info_iterator_t {
    xcb_dbe_swap_info_t *data;
    int                  rem;
    int                  index;
} xcb_dbe_swap_info_iterator_t;

/**
 * @brief xcb_dbe_buffer_attributes_t
 **/
typedef struct xcb_dbe_buffer_attributes_t {
    xcb_window_t window;
} xcb_dbe_buffer_attributes_t;

/**
 * @brief xcb_dbe_buffer_attributes_iterator_t
 **/
typedef struct xcb_dbe_buffer_attributes_iterator_t {
    xcb_dbe_buffer_attributes_t *data;
    int                          rem;
    int                          index;
} xcb_dbe_buffer_attributes_iterator_t;

/**
 * @brief xcb_dbe_visual_info_t
 **/
typedef struct xcb_dbe_visual_info_t {
    xcb_visualid_t visual_id;
    uint8_t        depth;
    uint8_t        perf_level;
    uint8_t        pad0[2];
} xcb_dbe_visual_info_t;

/**
 * @brief xcb_dbe_visual_info_iterator_t
 **/
typedef struct xcb_dbe_visual_info_iterator_t {
    xcb_dbe_visual_info_t *data;
    int                    rem;
    int                    index;
} xcb_dbe_visual_info_iterator_t;

/**
 * @brief xcb_dbe_visual_infos_t
 **/
typedef struct xcb_dbe_visual_infos_t {
    uint32_t n_infos;
} xcb_dbe_visual_infos_t;

/**
 * @brief xcb_dbe_visual_infos_iterator_t
 **/
typedef struct xcb_dbe_visual_infos_iterator_t {
    xcb_dbe_visual_infos_t *data;
    int                     rem;
    int                     index;
} xcb_dbe_visual_infos_iterator_t;

/** Opcode for xcb_dbe_bad_buffer. */
#define XCB_DBE_BAD_BUFFER 0

/**
 * @brief xcb_dbe_bad_buffer_error_t
 **/
typedef struct xcb_dbe_bad_buffer_error_t {
    uint8_t               response_type;
    uint8_t               error_code;
    uint16_t              sequence;
    xcb_dbe_back_buffer_t bad_buffer;
    uint16_t              minor_opcode;
    uint8_t               major_opcode;
} xcb_dbe_bad_buffer_error_t;

/**
 * @brief xcb_dbe_query_version_cookie_t
 **/
typedef struct xcb_dbe_query_version_cookie_t {
    unsigned int sequence;
} xcb_dbe_query_version_cookie_t;

/** Opcode for xcb_dbe_query_version. */
#define XCB_DBE_QUERY_VERSION 0

/**
 * @brief xcb_dbe_query_version_request_t
 **/
typedef struct xcb_dbe_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  major_version;
    uint8_t  minor_version;
    uint8_t  pad0[2];
} xcb_dbe_query_version_request_t;

/**
 * @brief xcb_dbe_query_version_reply_t
 **/
typedef struct xcb_dbe_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  major_version;
    uint8_t  minor_version;
    uint8_t  pad1[22];
} xcb_dbe_query_version_reply_t;

/** Opcode for xcb_dbe_allocate_back_buffer. */
#define XCB_DBE_ALLOCATE_BACK_BUFFER 1

/**
 * @brief xcb_dbe_allocate_back_buffer_request_t
 **/
typedef struct xcb_dbe_allocate_back_buffer_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_window_t          window;
    xcb_dbe_back_buffer_t buffer;
    uint8_t               swap_action;
    uint8_t               pad0[3];
} xcb_dbe_allocate_back_buffer_request_t;

/** Opcode for xcb_dbe_deallocate_back_buffer. */
#define XCB_DBE_DEALLOCATE_BACK_BUFFER 2

/**
 * @brief xcb_dbe_deallocate_back_buffer_request_t
 **/
typedef struct xcb_dbe_deallocate_back_buffer_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_dbe_back_buffer_t buffer;
} xcb_dbe_deallocate_back_buffer_request_t;

/** Opcode for xcb_dbe_swap_buffers. */
#define XCB_DBE_SWAP_BUFFERS 3

/**
 * @brief xcb_dbe_swap_buffers_request_t
 **/
typedef struct xcb_dbe_swap_buffers_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t n_actions;
} xcb_dbe_swap_buffers_request_t;

/** Opcode for xcb_dbe_begin_idiom. */
#define XCB_DBE_BEGIN_IDIOM 4

/**
 * @brief xcb_dbe_begin_idiom_request_t
 **/
typedef struct xcb_dbe_begin_idiom_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_dbe_begin_idiom_request_t;

/** Opcode for xcb_dbe_end_idiom. */
#define XCB_DBE_END_IDIOM 5

/**
 * @brief xcb_dbe_end_idiom_request_t
 **/
typedef struct xcb_dbe_end_idiom_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_dbe_end_idiom_request_t;

/**
 * @brief xcb_dbe_get_visual_info_cookie_t
 **/
typedef struct xcb_dbe_get_visual_info_cookie_t {
    unsigned int sequence;
} xcb_dbe_get_visual_info_cookie_t;

/** Opcode for xcb_dbe_get_visual_info. */
#define XCB_DBE_GET_VISUAL_INFO 6

/**
 * @brief xcb_dbe_get_visual_info_request_t
 **/
typedef struct xcb_dbe_get_visual_info_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t n_drawables;
} xcb_dbe_get_visual_info_request_t;

/**
 * @brief xcb_dbe_get_visual_info_reply_t
 **/
typedef struct xcb_dbe_get_visual_info_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t n_supported_visuals;
    uint8_t  pad1[20];
} xcb_dbe_get_visual_info_reply_t;

/**
 * @brief xcb_dbe_get_back_buffer_attributes_cookie_t
 **/
typedef struct xcb_dbe_get_back_buffer_attributes_cookie_t {
    unsigned int sequence;
} xcb_dbe_get_back_buffer_attributes_cookie_t;

/** Opcode for xcb_dbe_get_back_buffer_attributes. */
#define XCB_DBE_GET_BACK_BUFFER_ATTRIBUTES 7

/**
 * @brief xcb_dbe_get_back_buffer_attributes_request_t
 **/
typedef struct xcb_dbe_get_back_buffer_attributes_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_dbe_back_buffer_t buffer;
} xcb_dbe_get_back_buffer_attributes_request_t;

/**
 * @brief xcb_dbe_get_back_buffer_attributes_reply_t
 **/
typedef struct xcb_dbe_get_back_buffer_attributes_reply_t {
    uint8_t                     response_type;
    uint8_t                     pad0;
    uint16_t                    sequence;
    uint32_t                    length;
    xcb_dbe_buffer_attributes_t attributes;
    uint8_t                     pad1[20];
} xcb_dbe_get_back_buffer_attributes_reply_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_dbe_back_buffer_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_dbe_back_buffer_t)
 */
void
xcb_dbe_back_buffer_next (xcb_dbe_back_buffer_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_dbe_back_buffer_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_dbe_back_buffer_end (xcb_dbe_back_buffer_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_dbe_swap_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_dbe_swap_info_t)
 */
void
xcb_dbe_swap_info_next (xcb_dbe_swap_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_dbe_swap_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_dbe_swap_info_end (xcb_dbe_swap_info_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_dbe_buffer_attributes_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_dbe_buffer_attributes_t)
 */
void
xcb_dbe_buffer_attributes_next (xcb_dbe_buffer_attributes_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_dbe_buffer_attributes_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_dbe_buffer_attributes_end (xcb_dbe_buffer_attributes_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_dbe_visual_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_dbe_visual_info_t)
 */
void
xcb_dbe_visual_info_next (xcb_dbe_visual_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_dbe_visual_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_dbe_visual_info_end (xcb_dbe_visual_info_iterator_t i);

int
xcb_dbe_visual_infos_sizeof (const void  *_buffer);

xcb_dbe_visual_info_t *
xcb_dbe_visual_infos_infos (const xcb_dbe_visual_infos_t *R);

int
xcb_dbe_visual_infos_infos_length (const xcb_dbe_visual_infos_t *R);

xcb_dbe_visual_info_iterator_t
xcb_dbe_visual_infos_infos_iterator (const xcb_dbe_visual_infos_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_dbe_visual_infos_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_dbe_visual_infos_t)
 */
void
xcb_dbe_visual_infos_next (xcb_dbe_visual_infos_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_dbe_visual_infos_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_dbe_visual_infos_end (xcb_dbe_visual_infos_iterator_t i);

/**
 * @brief Queries the version of this extension
 *
 * @param c The connection
 * @param major_version The major version of the extension. Check that it is compatible with the XCB_DBE_MAJOR_VERSION that your code is compiled with.
 * @param minor_version The minor version of the extension. Check that it is compatible with the XCB_DBE_MINOR_VERSION that your code is compiled with.
 * @return A cookie
 *
 * Queries the version of this extension. You must do this before using any functionality it provides.
 *
 */
xcb_dbe_query_version_cookie_t
xcb_dbe_query_version (xcb_connection_t *c,
                       uint8_t           major_version,
                       uint8_t           minor_version);

/**
 * @brief Queries the version of this extension
 *
 * @param c The connection
 * @param major_version The major version of the extension. Check that it is compatible with the XCB_DBE_MAJOR_VERSION that your code is compiled with.
 * @param minor_version The minor version of the extension. Check that it is compatible with the XCB_DBE_MINOR_VERSION that your code is compiled with.
 * @return A cookie
 *
 * Queries the version of this extension. You must do this before using any functionality it provides.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_dbe_query_version_cookie_t
xcb_dbe_query_version_unchecked (xcb_connection_t *c,
                                 uint8_t           major_version,
                                 uint8_t           minor_version);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_dbe_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_dbe_query_version_reply_t *
xcb_dbe_query_version_reply (xcb_connection_t                *c,
                             xcb_dbe_query_version_cookie_t   cookie  /**< */,
                             xcb_generic_error_t            **e);

/**
 * @brief Allocates a back buffer
 *
 * @param c The connection
 * @param window The window to which to add the back buffer.
 * @param buffer The buffer id to associate with the back buffer.
 * @param swap_action The swap action most likely to be used to present this back buffer. This is only a hint, and does not preclude the use of other swap actions.
 * @return A cookie
 *
 * Associates \a buffer with the back buffer of \a window. Multiple ids may be associated with the back buffer, which is created by the first allocate call and destroyed by the last deallocate.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_dbe_allocate_back_buffer_checked (xcb_connection_t      *c,
                                      xcb_window_t           window,
                                      xcb_dbe_back_buffer_t  buffer,
                                      uint8_t                swap_action);

/**
 * @brief Allocates a back buffer
 *
 * @param c The connection
 * @param window The window to which to add the back buffer.
 * @param buffer The buffer id to associate with the back buffer.
 * @param swap_action The swap action most likely to be used to present this back buffer. This is only a hint, and does not preclude the use of other swap actions.
 * @return A cookie
 *
 * Associates \a buffer with the back buffer of \a window. Multiple ids may be associated with the back buffer, which is created by the first allocate call and destroyed by the last deallocate.
 *
 */
xcb_void_cookie_t
xcb_dbe_allocate_back_buffer (xcb_connection_t      *c,
                              xcb_window_t           window,
                              xcb_dbe_back_buffer_t  buffer,
                              uint8_t                swap_action);

/**
 * @brief Deallocates a back buffer
 *
 * @param c The connection
 * @param buffer The back buffer to deallocate.
 * @return A cookie
 *
 * Deallocates the given \a buffer. If \a buffer is an invalid id, a `BadBuffer` error is returned. Because a window may have allocated multiple back buffer ids, the back buffer itself is not deleted until all these ids are deallocated by this call.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_dbe_deallocate_back_buffer_checked (xcb_connection_t      *c,
                                        xcb_dbe_back_buffer_t  buffer);

/**
 * @brief Deallocates a back buffer
 *
 * @param c The connection
 * @param buffer The back buffer to deallocate.
 * @return A cookie
 *
 * Deallocates the given \a buffer. If \a buffer is an invalid id, a `BadBuffer` error is returned. Because a window may have allocated multiple back buffer ids, the back buffer itself is not deleted until all these ids are deallocated by this call.
 *
 */
xcb_void_cookie_t
xcb_dbe_deallocate_back_buffer (xcb_connection_t      *c,
                                xcb_dbe_back_buffer_t  buffer);

int
xcb_dbe_swap_buffers_sizeof (const void  *_buffer);

/**
 * @brief Swaps front and back buffers
 *
 * @param c The connection
 * @param n_actions Number of swap actions in \a actions.
 * @param actions List of windows on which to swap buffers.
 * @return A cookie
 *
 * Swaps the front and back buffers on the specified windows. The front and back buffers retain their ids, so that the window id continues to refer to the front buffer, while the back buffer id created by this extension continues to refer to the back buffer. Back buffer contents is moved to the front buffer. Back buffer contents after the operation depends on the given swap action. The optimal swap action depends on how each frame is rendered. For example, if the buffer is cleared and fully overwritten on every frame, the "untouched" action, which throws away the buffer contents, would provide the best performance. To eliminate visual artifacts, the swap will occure during the monitor VSync, if the X server supports detecting it.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_dbe_swap_buffers_checked (xcb_connection_t          *c,
                              uint32_t                   n_actions,
                              const xcb_dbe_swap_info_t *actions);

/**
 * @brief Swaps front and back buffers
 *
 * @param c The connection
 * @param n_actions Number of swap actions in \a actions.
 * @param actions List of windows on which to swap buffers.
 * @return A cookie
 *
 * Swaps the front and back buffers on the specified windows. The front and back buffers retain their ids, so that the window id continues to refer to the front buffer, while the back buffer id created by this extension continues to refer to the back buffer. Back buffer contents is moved to the front buffer. Back buffer contents after the operation depends on the given swap action. The optimal swap action depends on how each frame is rendered. For example, if the buffer is cleared and fully overwritten on every frame, the "untouched" action, which throws away the buffer contents, would provide the best performance. To eliminate visual artifacts, the swap will occure during the monitor VSync, if the X server supports detecting it.
 *
 */
xcb_void_cookie_t
xcb_dbe_swap_buffers (xcb_connection_t          *c,
                      uint32_t                   n_actions,
                      const xcb_dbe_swap_info_t *actions);

xcb_dbe_swap_info_t *
xcb_dbe_swap_buffers_actions (const xcb_dbe_swap_buffers_request_t *R);

int
xcb_dbe_swap_buffers_actions_length (const xcb_dbe_swap_buffers_request_t *R);

xcb_dbe_swap_info_iterator_t
xcb_dbe_swap_buffers_actions_iterator (const xcb_dbe_swap_buffers_request_t *R);

/**
 * @brief Begins a logical swap block
 *
 * @param c The connection
 * @return A cookie
 *
 * Creates a block of operations intended to occur together. This may be needed if window presentation requires changing buffers unknown to this extension, such as depth or stencil buffers.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_dbe_begin_idiom_checked (xcb_connection_t *c);

/**
 * @brief Begins a logical swap block
 *
 * @param c The connection
 * @return A cookie
 *
 * Creates a block of operations intended to occur together. This may be needed if window presentation requires changing buffers unknown to this extension, such as depth or stencil buffers.
 *
 */
xcb_void_cookie_t
xcb_dbe_begin_idiom (xcb_connection_t *c);

/**
 * @brief Ends a logical swap block
 *
 * @param c The connection
 * @return A cookie
 *
 * No description yet
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_dbe_end_idiom_checked (xcb_connection_t *c);

/**
 * @brief Ends a logical swap block
 *
 * @param c The connection
 * @return A cookie
 *
 * No description yet
 *
 */
xcb_void_cookie_t
xcb_dbe_end_idiom (xcb_connection_t *c);

int
xcb_dbe_get_visual_info_sizeof (const void  *_buffer);

/**
 * @brief Requests visuals that support double buffering
 *
 * @param c The connection
 * @return A cookie
 *
 * No description yet
 *
 */
xcb_dbe_get_visual_info_cookie_t
xcb_dbe_get_visual_info (xcb_connection_t     *c,
                         uint32_t              n_drawables,
                         const xcb_drawable_t *drawables);

/**
 * @brief Requests visuals that support double buffering
 *
 * @param c The connection
 * @return A cookie
 *
 * No description yet
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_dbe_get_visual_info_cookie_t
xcb_dbe_get_visual_info_unchecked (xcb_connection_t     *c,
                                   uint32_t              n_drawables,
                                   const xcb_drawable_t *drawables);

int
xcb_dbe_get_visual_info_supported_visuals_length (const xcb_dbe_get_visual_info_reply_t *R);

xcb_dbe_visual_infos_iterator_t
xcb_dbe_get_visual_info_supported_visuals_iterator (const xcb_dbe_get_visual_info_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_dbe_get_visual_info_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_dbe_get_visual_info_reply_t *
xcb_dbe_get_visual_info_reply (xcb_connection_t                  *c,
                               xcb_dbe_get_visual_info_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

/**
 * @brief Gets back buffer attributes
 *
 * @param c The connection
 * @param buffer The back buffer to query.
 * @return A cookie
 *
 * Returns the attributes of the specified \a buffer.
 *
 */
xcb_dbe_get_back_buffer_attributes_cookie_t
xcb_dbe_get_back_buffer_attributes (xcb_connection_t      *c,
                                    xcb_dbe_back_buffer_t  buffer);

/**
 * @brief Gets back buffer attributes
 *
 * @param c The connection
 * @param buffer The back buffer to query.
 * @return A cookie
 *
 * Returns the attributes of the specified \a buffer.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_dbe_get_back_buffer_attributes_cookie_t
xcb_dbe_get_back_buffer_attributes_unchecked (xcb_connection_t      *c,
                                              xcb_dbe_back_buffer_t  buffer);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_dbe_get_back_buffer_attributes_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_dbe_get_back_buffer_attributes_reply_t *
xcb_dbe_get_back_buffer_attributes_reply (xcb_connection_t                             *c,
                                          xcb_dbe_get_back_buffer_attributes_cookie_t   cookie  /**< */,
                                          xcb_generic_error_t                         **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
