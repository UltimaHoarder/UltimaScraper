import { createContext, useContext } from 'react';

/** undefined while the favourites status is loading. */
export const FavouritesEnabledContext = createContext<boolean | undefined>(false);

export const useFavouritesEnabled = () => useContext(FavouritesEnabledContext);
