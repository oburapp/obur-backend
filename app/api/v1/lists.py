"""List-facing endpoints, including list items, likes, and bookmarks."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.exceptions import (
    BookmarkNotFoundError,
    DuplicateListItemError,
    LikeNotFoundError,
    ListItemNotFoundError,
    ListNotFoundError,
    NotListOwnerError,
    VenueNotFoundError,
)
from app.models.user import User
from app.schemas.list import (
    ListCreateRequest,
    ListItemCreateRequest,
    ListItemMoveRequest,
    ListItemResponse,
    ListResponse,
    ListUpdateRequest,
)
from app.services import bookmark as bookmark_service
from app.services import like as like_service
from app.services import list as list_service

router = APIRouter(prefix="/lists", tags=["lists"])

_LIST_NOT_FOUND_DETAIL = "List not found"


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_list(
    payload: ListCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ListResponse:
    """Create an empty list."""
    venue_list = await list_service.create_list(
        session,
        user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        visibility=payload.visibility,
    )
    return ListResponse.model_validate(venue_list)


@router.get("/{list_id}")
async def get_list(
    list_id: UUID,
    viewer: User | None = Depends(get_optional_current_user),
    session: AsyncSession = Depends(get_session),
) -> ListResponse:
    """Return a single list. A private list is only visible to its
    owner or an admin — anyone else gets 404, the same as if it didn't
    exist.
    """
    try:
        venue_list = await list_service.get_list(session, list_id, viewer=viewer)
    except ListNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_LIST_NOT_FOUND_DETAIL
        ) from e
    return ListResponse.model_validate(venue_list)


@router.patch("/{list_id}")
async def update_list(
    list_id: UUID,
    payload: ListUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ListResponse:
    """Update a list's editable fields. Owner or admin only."""
    try:
        venue_list = await list_service.update_list(
            session,
            list_id,
            current_user=current_user,
            updates=payload.model_dump(exclude_unset=True),
        )
    except ListNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_LIST_NOT_FOUND_DETAIL
        ) from e
    except NotListOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    return ListResponse.model_validate(venue_list)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently delete a list and its items. Owner or admin only."""
    try:
        await list_service.delete_list(session, list_id, current_user=current_user)
    except ListNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_LIST_NOT_FOUND_DETAIL
        ) from e
    except NotListOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e


@router.get("/{list_id}/items")
async def list_items(
    list_id: UUID,
    viewer: User | None = Depends(get_optional_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ListItemResponse]:
    """List a list's items in order. 404s the same as `get_list` if the
    list isn't visible to `viewer`.
    """
    try:
        await list_service.get_list(session, list_id, viewer=viewer)
    except ListNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_LIST_NOT_FOUND_DETAIL
        ) from e
    items = await list_service.list_items_for_list(
        session, list_id, limit=limit, offset=offset
    )
    return [ListItemResponse.model_validate(item) for item in items]


@router.post("/{list_id}/items", status_code=status.HTTP_201_CREATED)
async def add_list_item(
    list_id: UUID,
    payload: ListItemCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ListItemResponse:
    """Add a venue to a list. Owner or admin only."""
    try:
        item = await list_service.add_list_item(
            session,
            list_id,
            current_user=current_user,
            venue_id=payload.venue_id,
            after_item_id=payload.after_item_id,
        )
    except (ListNotFoundError, VenueNotFoundError, ListItemNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except NotListOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except DuplicateListItemError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        ) from e
    return ListItemResponse.model_validate(item)


@router.patch("/{list_id}/items/{item_id}/move")
async def move_list_item(
    list_id: UUID,
    item_id: UUID,
    payload: ListItemMoveRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ListItemResponse:
    """Move an existing list item. Owner or admin only."""
    try:
        item = await list_service.move_list_item(
            session,
            list_id,
            item_id,
            current_user=current_user,
            after_item_id=payload.after_item_id,
        )
    except (ListNotFoundError, ListItemNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except NotListOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    return ListItemResponse.model_validate(item)


@router.delete("/{list_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_list_item(
    list_id: UUID,
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove an item from a list. Owner or admin only."""
    try:
        await list_service.remove_list_item(
            session, list_id, item_id, current_user=current_user
        )
    except (ListNotFoundError, ListItemNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except NotListOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e


@router.post("/{list_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def like_list(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Like a list. Idempotent. Liking a list you can't see isn't
    possible — same visibility rules as `get_list`.
    """
    try:
        await like_service.like_list(session, list_id, current_user=current_user)
    except ListNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_LIST_NOT_FOUND_DETAIL
        ) from e


@router.delete("/{list_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_list(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Un-like a list."""
    try:
        await like_service.unlike_list(session, list_id, current_user=current_user)
    except LikeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="List not liked"
        ) from e


@router.post("/{list_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def bookmark_list(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Bookmark a list. Idempotent, private — never a social signal."""
    try:
        await bookmark_service.bookmark_list(
            session, list_id, current_user=current_user
        )
    except ListNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_LIST_NOT_FOUND_DETAIL
        ) from e


@router.delete("/{list_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def unbookmark_list(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove a list bookmark."""
    try:
        await bookmark_service.unbookmark_list(
            session, list_id, current_user=current_user
        )
    except BookmarkNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="List not bookmarked"
        ) from e
