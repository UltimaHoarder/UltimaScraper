import { expect, test, type Locator } from '@playwright/test';
import { installApiMocks, seedConfiguredApp, backendPath } from './helpers';

async function userCardAppearance(card: Locator) {
  return card.evaluate(element => {
    const style = (selector: string) => {
      const node = element.querySelector(selector)!;
      if (!node) return null;
      const css = getComputedStyle(node);
      return { padding: css.padding, fontSize: css.fontSize, display: css.display, gap: css.gap };
    };
    const grid = getComputedStyle(element.closest('[role="tabpanel"], .users-grid, .subscriptions-grid')!);
    return { header: style('.card-header'), avatar: style('.avatar'), stats: style('.stats'),
      identity: style('.username-link'), actions: style('.card-actions'), scrape: style('.btn-scrape'),
      subscribe: style('.btn-subscribe'), watch: style('.btn-watch'), gridGap: grid.gap, columns: grid.gridTemplateColumns };
  });
}

test('favourites never falls back to the legacy users endpoint when canonical reads are unavailable', async ({ page }) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//, () => {});
  const legacyUserRequests: string[] = [];
  page.on('request', request => {
    if (backendPath(request.url()) === '/api/v1/users') legacyUserRequests.push(request.url());
  });
  await page.route('**/api/v1/favourites**', async route => {
    if (backendPath(route.request().url()).endsWith('/status')) {
      return route.fulfill({ json: { enabled: false } });
    }
    return route.fulfill({ status: 503, json: { detail: 'Unified favourites await migration and activation' } });
  });
  await page.goto('/favourites');
  await expect(page.getByRole('tab', { name: 'Users', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  await expect(page.getByText('No favourites found.', { exact: true })).toHaveCount(0);
  expect(legacyUserRequests).toEqual([]);
});

test('unified favourites preserves type/site filters, availability and keyboard removal', async ({ page }, info) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//, () => {});
  const user = (id: number, site: string) => ({id,user_id:id,username:`creator_${id}`,name:'Creator',description:null,
    sex:null,gender:null,avatar_url:null,header_url:null,price:0,post_count:2,media_count:0,image_count:0,video_count:0,
    favorite:true,is_active:id===1,is_subscribed:false,is_pending_order:false,site,downloaded_at:null,last_checked_at:null});
  let items = [
    {id:1,site:'onlyfans',entity_type:'user',entity_id:1,created_at:'2023-06-15T05:00:00Z',created_at_source:'user_downloaded_at',availability:'available',entity:user(1,'onlyfans')},
    {id:2,site:'fansly',entity_type:'user',entity_id:2,created_at:'2026-10-13T00:00:00Z',created_at_source:'migration_fallback',availability:'inactive',entity:user(2,'fansly')},
    {id:3,site:'onlyfans',entity_type:'story',entity_id:3,created_at:'2026-10-13T00:00:00Z',created_at_source:'added',availability:'expired',entity:{id:3,user_id:1,username:'creator_1',site:'onlyfans',content_type:'story',text:null,price:0,paid:null,deleted:false,archived:false,media_count:0,media:[],expires_at:'2026-01-01T00:00:00Z',created_at:'2025-12-31T00:00:00Z',favorite:true}},
  ];
  await page.route('**/api/v1/favourites**', async route => {
    const url = new URL(route.request().url());
    const path = backendPath(url);
    const filtered = items.filter(item => !url.searchParams.get('site') || item.site===url.searchParams.get('site'));
    if (path.endsWith('/status')) return route.fulfill({json:{enabled:true}});
    if (path.endsWith('/counts')) {
      expect(url.searchParams.has('entity_type')).toBe(false);
      return route.fulfill({json:{total:filtered.length,by_type:{user:filtered.filter(i=>i.entity_type==='user').length,post:0,story:filtered.filter(i=>i.entity_type==='story').length,message:0}}});
    }
    if (path.endsWith('/states')) {
      const {keys} = route.request().postDataJSON() as {keys:{site:string;entity_type:string;entity_id:number}[]};
      return route.fulfill({json:{states:keys.map(key=>({...key,favourited:items.some(item=>item.site===key.site&&item.entity_type===key.entity_type&&item.entity_id===key.entity_id),favourite_id:null,created_at:null,created_at_source:null}))}});
    }
    if (route.request().method()==='DELETE') {
      const [,site,entity_type,entity_id] = path.match(/favourites\/([^/]+)\/([^/]+)\/(\d+)$/)!;
      items=items.filter(item=>!(item.site===site&&item.entity_type===entity_type&&item.entity_id===Number(entity_id)));
      return route.fulfill({json:{site,entity_type,entity_id:Number(entity_id),favourited:false,favourite_id:null,created_at:null,created_at_source:null}});
    }
    return route.fulfill({json:{items:filtered.filter(item=>!url.searchParams.get('entity_type')||item.entity_type===url.searchParams.get('entity_type')),has_more:false,next_cursor:null}});
  });
  const errors: string[]=[];
  page.on('pageerror', error=>errors.push(error.message));
  const requests: { path: string; body: unknown; site: string | null }[] = [];
  await page.route('**/api/v1/users/1/eligible-auths?*', route => route.fulfill({ json: {
    auths: [{ auth_id: 7, auth_username: 'Account Seven', is_active: true }, { auth_id: 8, auth_username: 'Account Eight', is_active: true }],
  } }));
  await page.route('**/api/v1/webhooks/watch/1?*', async route => {
    requests.push({ path: backendPath(route.request().url()), body: null, site: new URL(route.request().url()).searchParams.get('site') });
    return route.fulfill({ json: { user_id: 1, watched: route.request().method() === 'PUT', message: 'Watch updated' } });
  });
  await page.route('**/api/v1/jobs', async route => {
    requests.push({ path: '/api/v1/jobs', body: route.request().postDataJSON(), site: null });
    return route.fulfill({ json: { job_name: 'Favourite scrape' } });
  });
  await page.route('**/api/v1/orders/performers', async route => {
    requests.push({ path: '/api/v1/orders/performers', body: route.request().postDataJSON(), site: null });
    return route.fulfill({ json: { success: true, message: 'Subscription order queued' } });
  });
  await page.route('**/api/v1/users/1?*', async route => {
    requests.push({ path: '/api/v1/users/1', body: route.request().postDataJSON(), site: new URL(route.request().url()).searchParams.get('site') });
    return route.fulfill({ json: { success: true, user_id: 1 } });
  });
  await page.goto('/users?site=onlyfans');
  await expect(page.locator('.users-grid .user-card').first()).toBeVisible();
  const usersAppearance = await userCardAppearance(page.locator('.users-grid .user-card').first());
  await page.goto('/favourites');
  await expect(page.getByRole('tab',{name:'Users (2)'})).toHaveAttribute('aria-selected','true');
  await expect(page.locator('.users-metrics')).toHaveCSS('display', 'grid');
  const favouriteCard = page.locator('.user-card').first();
  const {columns:favouriteColumns,...favouriteAppearance}=await userCardAppearance(favouriteCard);
  const {columns:userColumns,...userAppearance}=usersAppearance;
  expect(favouriteAppearance).toEqual(userAppearance);
  // Chromium distributes fractional grid pixels differently across otherwise
  // identical tracks; compare widths within 0.05 px, retaining track counts.
  const favouriteWidths=favouriteColumns.split(' ').map(Number.parseFloat);
  const userWidths=userColumns.split(' ').map(Number.parseFloat);
  expect(favouriteWidths).toHaveLength(userWidths.length);
  favouriteWidths.forEach((width,index)=>expect(width).toBeCloseTo(userWidths[index],1));
  await expect(page.locator('.favourite-entry-meta')).toHaveCount(0);
  await expect(favouriteCard.getByRole('button', { name: 'View', exact: true })).toHaveCount(0);
  await expect(page.locator('.badge.status').filter({hasText:'Inactive'})).toBeVisible();
  const remove=page.getByRole('button',{name:'Remove favourite user 1'});
  await expect(remove).toHaveAttribute('title', /Inherited user download date/);
  await expect(page.getByRole('button', { name: 'Remove favourite user 2' })).toHaveAttribute('title', /Migration fallback/);
  await page.screenshot({path:info.outputPath('favourites-users.png'),fullPage:true});
  await favouriteCard.getByRole('button', { name: '+ Watch', exact: true }).click();
  await expect(favouriteCard.getByRole('button', { name: '🚫 Unwatch', exact: true })).toBeVisible();
  await favouriteCard.getByRole('button', { name: '🚫 Unwatch', exact: true }).click();
  await expect(favouriteCard.getByRole('button', { name: '+ Watch', exact: true })).toBeVisible();
  await expect(favouriteCard.locator('.card-actions .favourite-button')).toHaveCount(0);
  const positions = await favouriteCard.evaluate(card => ({
    username: card.querySelector('.username-link')!.getBoundingClientRect().right,
    indicators: card.querySelector('.badges')!.getBoundingClientRect().left,
  }));
  expect(positions.indicators).toBeGreaterThanOrEqual(positions.username);
  await favouriteCard.getByRole('button', { name: 'Download', exact: true }).click();
  await expect(page.getByRole('heading', { name: '🔐 Select Auth for @creator_1' })).toBeVisible();
  await page.getByRole('button', { name: 'Account Eight', exact: false }).click();
  await expect.poll(() => requests.filter(request => request.path === '/api/v1/jobs').length).toBe(1);
  expect(requests.find(request => request.path === '/api/v1/jobs')?.body).toMatchObject({
    tasks: [{ task_type: 'scrape_and_download', params: { site: 'onlyfans', username: 'creator_1', auth_id: 8 } }],
  });
  await favouriteCard.getByRole('button', { name: 'Subscribe', exact: true }).click();
  await expect.poll(() => requests.some(request => request.path === '/api/v1/orders/performers')).toBe(true);
  expect(requests.find(request => request.path === '/api/v1/orders/performers')?.body).toMatchObject({ user_id: 1, site: 'onlyfans', auto_execute: false });
  await favouriteCard.getByRole('button', { name: 'More actions', exact: true }).click();
  await favouriteCard.getByRole('button', { name: /Edit User/ }).click();
  await expect(page.getByRole('heading', { name: 'Edit User @creator_1' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Updated creator');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Edit User @creator_1' })).toHaveCount(0);
  expect(requests.find(request => request.path === '/api/v1/users/1')).toMatchObject({ site: 'onlyfans', body: { name: 'Updated creator' } });
  await remove.focus();
  await page.keyboard.press('Enter');
  await expect(remove).toHaveCount(0);
  await expect(page.getByRole('tab',{name:'Users (1)'})).toBeVisible();
  await page.getByRole('tab',{name:'Stories (1)'}).click();
  await expect(page.getByText('expired',{exact:true})).toBeVisible();
  await expect(page.locator('.content-card-header')).toHaveCSS('display', 'flex');
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('favourites-stories.png'),fullPage:true});
  await page.getByRole('combobox',{name:'Favourite site'}).selectOption('fansly');
  await expect(page.getByText('No favourites found.')).toBeVisible();
  await page.getByRole('tab',{name:'Users (1)'}).click();
  await expect(page.getByRole('button',{name:'Remove favourite user 2'})).toBeVisible();
  expect(errors).toEqual([]);
});

test('subscriptions shares user card styling and header controls with Users', async ({ page }) => {
  await seedConfiguredApp(page, {theme:'ultima-atlas'});
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//, () => {});
  await page.route('**/api/v1/favourites**', async route => {
    if (backendPath(route.request().url()).endsWith('/status')) return route.fulfill({json:{enabled:true}});
    const keys = route.request().postDataJSON()?.keys || [];
    return route.fulfill({json:{states:keys.map((key: object) => ({...key, favourited:false, favourite_id:null,created_at:null,created_at_source:null}))}});
  });
  await page.goto('/users?site=onlyfans');
  const card = page.locator('.user-card').first();
  await expect(card).toBeVisible();
  const users = await userCardAppearance(card);
  await page.goto('/subscriptions?site=onlyfans');
  const subscription = page.locator('.subscriptions-grid .user-card').first();
  await expect(subscription).toBeVisible();
  const subs = await userCardAppearance(subscription);
  for (const key of ['header','avatar','stats','identity','actions','scrape','watch'] as const) {
    expect(subs[key]).toEqual(users[key]);
  }
  await expect(subscription.locator('.badges .favourite-control')).toBeVisible();
  await expect(subscription.locator('.card-actions .favourite-control')).toHaveCount(0);
  await expect(subscription.getByRole('button', {name:'Download',exact:true})).toBeVisible();
  const positions = await subscription.evaluate(card => ({
    identity: card.querySelector('.username-link')!.getBoundingClientRect().right,
    badges: card.querySelector('.badges')!.getBoundingClientRect().left,
  }));
  expect(positions.badges).toBeGreaterThanOrEqual(positions.identity);
});

test('favourites centers categories, scrolls batches and shares advanced filters with counts', async ({page}, info) => {
  await seedConfiguredApp(page,{theme:'ultima-atlas'});
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//,() => {});
  const all = Array.from({length:110},(_,index) => {
    const id=index+1;
    return {id,site:'onlyfans',entity_type:'user',entity_id:id,created_at:'2026-10-13T00:00:00Z',created_at_source:'added',availability:'available',
      entity:{id,user_id:id,site:'onlyfans',username:'saved_'+id,name:'Saved creator '+id,description:'Cached archive profile',
        avatar_url:null,header_url:null,price:id%10,post_count:20,image_count:10,video_count:5,media_count:15,
        favorite:true,is_active:true,is_subscribed:false,is_pending_order:false,last_checked_at:'2026-10-13T00:00:00Z',downloaded_at:null}};
  });
  const pages:URL[]=[];
  const counts:URL[]=[];
  await page.route('**/api/v1/favourites**',async route => {
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('/status')) return route.fulfill({json:{enabled:true}});
    if(url.pathname.endsWith('/states')) {
      const {keys}=route.request().postDataJSON();
      return route.fulfill({json:{states:keys.map((key:object)=>({...key,favourited:true,favourite_id:null,created_at:null,created_at_source:null}))}});
    }
    const filtered=all.filter(item => (!url.searchParams.has('min_price') || item.entity.price>=Number(url.searchParams.get('min_price'))));
    if(url.pathname.endsWith('/counts')) {
      counts.push(url);
      return route.fulfill({json:{total:filtered.length,by_type:{user:filtered.length,post:0,story:0,message:0}}});
    }
    pages.push(url);
    const offset=Number(url.searchParams.get('cursor') ?? 0);
    const items=filtered.slice(offset,offset+50);
    return route.fulfill({json:{items,has_more:offset+50<filtered.length,next_cursor:offset+50<filtered.length ? String(offset+50):null}});
  });
  await page.goto('/favourites');
  await expect(page.locator('.favourite-entry')).toHaveCount(50);
  await expect(page.getByRole('tablist',{name:'Favourite type'})).toHaveCSS('justify-content','center');
  const centered = await page.getByRole('tablist').evaluate(list => {
    const parent=list.getBoundingClientRect();
    const rows=new Map<number,DOMRect[]>();
    for(const element of list.children) {
      const rect=element.getBoundingClientRect(),top=Math.round(rect.top);
      rows.set(top,[...(rows.get(top)||[]),rect]);
    }
    return [...rows.values()].every(row => Math.abs((Math.min(...row.map(r=>r.left))+Math.max(...row.map(r=>r.right)))/2-(parent.left+parent.right)/2)<2);
  });
  expect(centered).toBe(true);
  await page.locator('.users-scroll-sentinel').scrollIntoViewIfNeeded();
  await expect(page.locator('.favourite-entry')).toHaveCount(100);
  expect(pages.map(url=>url.searchParams.get('cursor'))).toEqual([null,'50']);
  await expect(page.getByRole('link',{name:'@saved_1',exact:true})).toHaveCount(1);
  await page.locator('.users-scroll-sentinel').scrollIntoViewIfNeeded();
  await expect(page.locator('.favourite-entry')).toHaveCount(110);
  await expect(page.getByText('All favourites loaded')).toBeVisible();
  await page.getByRole('button',{name:'Filters',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog',{name:'Favourite filters'})).toBeVisible();
  await page.getByRole('spinbutton',{name:'Minimum price'}).fill('8');
  await page.getByRole('combobox',{name:'Favourite availability'}).selectOption('available');
  const sexRow=page.locator('.content-library-filter-row').filter({has:page.getByText('Sex',{exact:true})});
  await sexRow.getByRole('checkbox',{name:'Female',exact:true}).check();
  await sexRow.getByRole('checkbox',{name:'Unset',exact:true}).check();
  await page.getByRole('button',{name:'Apply',exact:true}).click();
  await expect(page.locator('.favourite-entry')).toHaveCount(22);
  await expect(page.getByRole('tab',{name:'Users (22)'})).toBeVisible();
  expect(pages.at(-1)?.searchParams.get('cursor')).toBeNull();
  expect(pages.at(-1)?.searchParams.get('min_price')).toBe('8');
  expect(pages.at(-1)?.searchParams.getAll('sex').sort()).toEqual(['-1','0']);
  expect(counts.at(-1)?.searchParams.get('min_price')).toBe('8');
  expect(counts.at(-1)?.searchParams.has('entity_type')).toBe(false);
  await expect(page.getByRole('button',{name:'Next',exact:true})).toHaveCount(0);
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('button',{name:'Filters (3)'}).click();
  await page.screenshot({path:info.outputPath('favourites-filters.png'),fullPage:true});
  if(info.project.name==='desktop') await page.screenshot({path:'../docs/favourites-filters-2026-10-13.png'});
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Filters (3)'})).toBeFocused();
  await page.getByRole('button',{name:'Filters (3)'}).click();
  await page.getByRole('button',{name:'Clear',exact:true}).click();
  await page.getByRole('button',{name:'Apply',exact:true}).click();
  await expect(page.getByRole('button',{name:'Filters',exact:true})).toBeVisible();
  await expect(page.getByRole('tab',{name:'Users (110)'})).toBeVisible();
});
